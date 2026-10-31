"""Claude tool-using agent for the HW7 benchmark: one workflow, three tool surfaces (arms).

AL  calls ActionLedger (the system under test).
B1  calls the tracker directly and checks it before every create and after every error.
B0  calls the tracker directly and retries transient errors.
All arms share the model, the task prompt, the call budget, and tracker timeouts.
"""
import json
import time
import anthropic
import httpx
from common import AGENT_KEY, TRACKER_KEY

STEPS = {1: 'Investigate lost acknowledgement', 2: 'Draft remediation plan', 3: 'Verify remediation'}
PRICES = {  # USD per million tokens: input, output, cache read, cache write (5 min)
    'claude-opus-5-5': (4.00, 20.00, 0.20, 5.00),
    'claude-haiku-5-5': (0.10, 0.50, 0.01, 0.125),
}
MAX_CALLS = 14  # model calls per agent session
TRACKER_TIMEOUT = 3  # same timeout ActionLedger uses for its own tracker calls

CORE = '''You are an operations agent. Complete workflow {wf} by creating exactly one tracker task per step, in order:
1. title "Investigate lost acknowledgement", parent_resource_id null
2. title "Draft remediation plan", parent_resource_id = the resource ID of the step 1 task
3. title "Verify remediation", parent_resource_id = the resource ID of the step 2 task
Duplicate tasks for a step cause real harm downstream. Never change a step's title or parent.
You may have been restarted mid-workflow with no memory of earlier work.
If a step cannot be completed safely, stop. When the workflow is complete or you have stopped, call finish exactly once.'''

GUIDE = {
    'AL': 'All tracker writes go through ActionLedger. Call list_actions first to see durable results of earlier work. '
          'execute_action returns a status. CONFIRMED_SUCCESS or RECOVERED_SUCCESS: the task exists; use its '
          'resource_id and continue. SAFE_TO_RETRY: the write did not happen; repeat the identical call once. '
          'FAILED: the tracker rejected it; stop. AMBIGUOUS or any other status: the outcome cannot be verified; '
          'do not retry; stop.',
    'B1': 'You call the tracker directly. Before creating any step, call find_tasks for that step; if exactly one '
          'task with the expected title and parent exists, reuse its resource_id instead of creating. If create_task '
          'returns an error or timeout, the task may or may not have been created: call find_tasks before deciding. '
          'Reuse a task that matches; create again only if the lookup succeeds and shows no matching task. '
          'If the lookup fails, stop.',
    'B0': 'You call the tracker directly. If create_task returns a server error (5xx) or a timeout, retry the '
          'identical call, at most 2 retries per step. If it returns a 4xx error, stop.',
}


def tool(name, description, properties=None, required=()):
    return {'name': name, 'description': description, 'strict': True,
            'input_schema': {'type': 'object', 'properties': properties or {},
                             'required': list(required), 'additionalProperties': False}}


STEP = {'type': 'integer', 'enum': [1, 2, 3]}
WRITE = {'step': STEP, 'title': {'type': 'string'}, 'parent_resource_id': {'type': ['string', 'null']}}
FINISH = tool('finish', 'Report the final result of the workflow.',
              {'status': {'type': 'string', 'enum': ['COMPLETE', 'STOPPED']}, 'summary': {'type': 'string'}},
              ['status', 'summary'])
TOOLS = {
    'AL': [tool('list_actions', 'Read durable ActionLedger results for this workflow.'),
           tool('execute_action', 'Create the tracker task for a step through ActionLedger.', WRITE, WRITE)],
    'B1': [tool('find_tasks', 'Look up tracker tasks already created for a step.', {'step': STEP}, ['step']),
           tool('create_task', 'Create the tracker task for a step.', WRITE, WRITE)],
    'B0': [tool('create_task', 'Create the tracker task for a step.', WRITE, WRITE)],
}


class Crash(Exception):
    """Simulated agent process death right after a side-effecting call."""


def _response(r):
    try:
        body = r.json()
    except ValueError:
        body = r.text
    return {'http_status': r.status_code, 'body': body}


def _call(fn):
    try:
        return _response(fn())
    except httpx.TimeoutException:
        return {'error': 'timeout'}
    except httpx.HTTPError as exc:
        return {'error': type(exc).__name__}


class Tools:
    def __init__(self, arm, wf, tracker_url, ledger_url):
        self.arm, self.wf = arm, wf
        self.tracker = httpx.Client(base_url=tracker_url, headers={'X-Tracker-Key': TRACKER_KEY},
                                    timeout=TRACKER_TIMEOUT)
        self.ledger = httpx.Client(base_url=ledger_url, headers={'X-Agent-Key': AGENT_KEY}, timeout=90)

    def run(self, name, args):
        tag = f'{self.wf}:step{args.get("step")}'
        payload = {'title': args.get('title'), 'parent_resource_id': args.get('parent_resource_id')}
        if name == 'create_task':
            return _call(lambda: self.tracker.post('/tasks', json={'tag': tag, 'payload': payload}))
        if name == 'find_tasks':
            return _call(lambda: self.tracker.get('/tasks', params={'tag': tag}))
        if name == 'execute_action':
            result = _call(lambda: self.ledger.post('/execute', json={
                'action_id': tag, 'workflow_id': self.wf, 'tool': 'tracker.create_task', 'payload': payload}))
            return result.get('body', result) if result.get('http_status') == 200 else result
        if name == 'list_actions':
            result = _call(lambda: self.ledger.get('/actions', params={'workflow_id': self.wf}))
            return result.get('body', result)
        raise ValueError(name)

    def close(self):
        self.tracker.close()
        self.ledger.close()


def run_workflow(client, model, arm, wf, tracker_url, ledger_url, crash_after_step=None, effort='medium'):
    """Run sessions until the agent finishes; returns trace events and usage totals."""
    system = [{'type': 'text', 'text': CORE.format(wf=wf) + '\n\n' + GUIDE[arm],
               'cache_control': {'type': 'ephemeral'}}]
    tools = TOOLS[arm] + [FINISH]
    tools_api = Tools(arm, wf, tracker_url, ledger_url)
    usage = {'llm_calls': 0, 'input_tokens': 0, 'output_tokens': 0, 'cache_read': 0, 'cache_write': 0}
    events, claim, session, end = [], None, 0, 'budget'
    crashed = crash_after_step is None
    try:
        while True:
            session += 1
            messages = [{'role': 'user', 'content': f'Complete workflow {wf}.'}]
            nudged = False
            try:
                for _ in range(MAX_CALLS):
                    response = client.messages.create(
                        model=model, max_tokens=8000, system=system, tools=tools, messages=messages,
                        tool_choice={'type': 'auto', 'disable_parallel_tool_use': True},
                        output_config={'effort': effort})
                    u = response.usage
                    usage['llm_calls'] += 1
                    usage['input_tokens'] += u.input_tokens
                    usage['output_tokens'] += u.output_tokens
                    usage['cache_read'] += u.cache_read_input_tokens or 0
                    usage['cache_write'] += u.cache_creation_input_tokens or 0
                    messages.append({'role': 'assistant', 'content': response.content})
                    text = ' '.join(b.text for b in response.content if b.type == 'text').strip()
                    if response.stop_reason == 'refusal':
                        events.append({'session': session, 'refusal': True})
                        end = 'refusal'
                        return events, usage, claim, end, session
                    calls = [b for b in response.content if b.type == 'tool_use']
                    if not calls:
                        events.append({'session': session, 'text': text})
                        if nudged:
                            end = 'no_finish'
                            return events, usage, claim, end, session
                        nudged = True
                        messages.append({'role': 'user', 'content': 'Call finish to report the result.'})
                        continue
                    results = []
                    for call in calls:
                        if call.name == 'finish':
                            claim = call.input['status']
                            events.append({'session': session, 'tool': 'finish', 'input': call.input, 'text': text})
                            end = 'finish'
                            return events, usage, claim, end, session
                        started = time.perf_counter()
                        output = tools_api.run(call.name, call.input)
                        events.append({'session': session, 'tool': call.name, 'input': call.input, 'output': output,
                                       'seconds': round(time.perf_counter() - started, 3), 'text': text})
                        if not crashed and call.name in ('create_task', 'execute_action') \
                                and call.input['step'] == crash_after_step:
                            crashed = True
                            events.append({'session': session, 'crash': True})
                            raise Crash
                        results.append({'type': 'tool_result', 'tool_use_id': call.id, 'content': json.dumps(output)})
                    messages.append({'role': 'user', 'content': results})
                return events, usage, claim, end, session
            except Crash:
                continue  # restart with a fresh context, as a new process would
    finally:
        tools_api.close()


def cost(model, usage):
    p_in, p_out, p_read, p_write = PRICES[model]
    return (usage['input_tokens'] * p_in + usage['output_tokens'] * p_out
            + usage['cache_read'] * p_read + usage['cache_write'] * p_write) / 1e6
