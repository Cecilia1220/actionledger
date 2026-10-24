"""A real OpenAI tool-calling client, bounded to 8 turns. No scripted fallback."""
import json
import os
from openai import OpenAI
import httpx
from common import AGENT_KEY, DATA

SUCCESS = {'CONFIRMED_SUCCESS', 'RECOVERED_SUCCESS'}


def tool(name, description, properties, required):
    return {'type': 'function', 'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties,
                           'required': required, 'additionalProperties': False}, 'strict': True}


def run_agent(workflow_id, ledger_url='http://127.0.0.1:8000'):
    if not os.getenv('OPENAI_API_KEY'):
        raise RuntimeError('Add OPENAI_API_KEY to actionledger/.env, then run python demo.py')
    tools = [tool('execute_action', 'Create a tracker task through ActionLedger. Reuse deterministic IDs.',
                  {'step': {'type': 'integer', 'enum': [1, 2]}, 'title': {'type': 'string'},
                   'parent_resource_id': {'type': ['string', 'null']}},
                  ['step', 'title', 'parent_resource_id']),
             tool('list_actions', 'Read durable workflow results after a restart.', {}, [])]
    messages = [{'role': 'system', 'content': (
        'You are an ops agent using ActionLedger. First read list_actions. Create step 1 with title '
        'Investigate lost acknowledgement and null parent. After a successful result, create step 2 '
        'with title Follow up on recovered task and parent_resource_id equal to step 1 resource_id. '
        'Only continue after CONFIRMED_SUCCESS or RECOVERED_SUCCESS. SAFE_TO_RETRY permits one '
        'retry with identical arguments. For AMBIGUOUS or FAILED, stop and explain. '
        'Never change a payload bound to an existing action ID. Finish with a brief result summary.')},
                {'role': 'user', 'content': f'Complete the two-step workflow {workflow_id}.'}]
    client = OpenAI(timeout=45, max_retries=0)
    trace = []
    step1_id = None
    with httpx.Client(base_url=ledger_url, headers={'X-Agent-Key': AGENT_KEY}, timeout=15) as http:
        for _ in range(8):
            response = client.responses.create(model=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
                                               input=messages, tools=tools, parallel_tool_calls=False)
            messages.extend(response.output)
            calls = [o for o in response.output if o.type == 'function_call']
            if not calls:
                print('AGENT:', response.output_text, flush=True)
                trace.append({'final': response.output_text})
                break
            for call in calls:
                args = json.loads(call.arguments)
                print(f'AGENT tool call: {call.name} {json.dumps(args)}', flush=True)
                if call.name == 'list_actions':
                    result = http.get('/actions', params={'workflow_id': workflow_id})
                elif call.name == 'execute_action':
                    # Enforce the dependency independently of what the model claims.
                    if args['step'] == 2 and (not step1_id or args['parent_resource_id'] != step1_id):
                        raise RuntimeError('Agent attempted step 2 without the verified step 1 resource ID')
                    result = http.post('/execute', json={
                        'action_id': f'{workflow_id}:step{args["step"]}', 'workflow_id': workflow_id,
                        'tool': 'tracker.create_task', 'payload': {
                            'title': args['title'], 'parent_resource_id': args['parent_resource_id']}})
                else:
                    raise RuntimeError('Unrecognized tool')
                result.raise_for_status()
                output = result.json()
                if call.name == 'list_actions':
                    for action in output['actions']:
                        if action['action_id'] == f'{workflow_id}:step1' and action['status'] in SUCCESS:
                            step1_id = action['resource_id']
                elif args['step'] == 1 and output['status'] in SUCCESS:
                    step1_id = output['resource_id']
                print('TOOL result:', json.dumps(output), flush=True)
                trace.append({'tool': call.name, 'arguments': args, 'result': output})
                messages.append({'type': 'function_call_output', 'call_id': call.call_id,
                                 'output': json.dumps(output)})
        else:
            raise RuntimeError('Agent exceeded the 8-turn budget')
    (DATA / f'{workflow_id}-agent.json').write_text(json.dumps(trace, indent=2))
    return trace
