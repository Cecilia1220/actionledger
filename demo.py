"""Start isolated local services, run demo, assert actual tracker state, cleanly stop."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import httpx
from common import AGENT_KEY, TRACKER_KEY, DATA

ROOT = Path(__file__).parent


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@contextmanager
def services(data_dir):
    tracker_port, ledger_port = free_port(), free_port()
    tracker_url, ledger_url = f'http://127.0.0.1:{tracker_port}', f'http://127.0.0.1:{ledger_port}'
    env = dict(os.environ, DATA_DIR=str(data_dir), TRACKER_URL=tracker_url)
    processes = []
    log = (data_dir / 'services.log').open('w')
    try:
        for module, port in [('mock_tracker', tracker_port), ('ledger', ledger_port)]:
            p = subprocess.Popen([sys.executable, '-m', 'uvicorn', f'{module}:app',
                                  '--host', '127.0.0.1', '--port', str(port), '--workers', '1'],
                                 cwd=ROOT, env=env, stdout=log, stderr=log)
            processes.append(p)
            for _ in range(100):
                if p.poll() is not None:
                    raise RuntimeError(f'{module} exited; see {data_dir}/services.log')
                try:
                    if httpx.get(f'http://127.0.0.1:{port}/health', timeout=.3).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError(f'{module} did not start')
        with httpx.Client(base_url=ledger_url, headers={'X-Agent-Key': AGENT_KEY}, timeout=15) as ledger:
            with httpx.Client(base_url=tracker_url, headers={'X-Tracker-Key': TRACKER_KEY}, timeout=15) as tracker:
                yield ledger, tracker, ledger_url
    finally:
        for p in reversed(processes):
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        log.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scripted', action='store_true', help='Infrastructure smoke demo only; NOT an LLM demo')
    args = parser.parse_args()
    if not args.scripted and not os.getenv('OPENAI_API_KEY'):
        sys.exit('Missing OPENAI_API_KEY. Fill .env, then rerun. Use --scripted only for infrastructure checks.')
    workflow = 'demo-' + uuid.uuid4().hex[:8]
    run_dir = DATA / workflow
    run_dir.mkdir()
    print('ActionLedger |', 'SCRIPTED infrastructure check (no LLM)' if args.scripted else 'LIVE OpenAI tool-using agent', flush=True)
    with services(run_dir) as (ledger, tracker, url):
        tracker.post('/faults', json={'mode': 'lost_ack'}).raise_for_status()
        if args.scripted:
            request = {'action_id': workflow + ':step1', 'workflow_id': workflow,
                       'payload': {'title': 'Investigate lost acknowledgement', 'parent_resource_id': None}}
            first = ledger.post('/execute', json=request).json()
            print('Lost-ack recovery:', json.dumps(first), flush=True)
            assert first['status'] == 'RECOVERED_SUCCESS', first
            assert ledger.post('/execute', json=request).json() == first
            request.update(action_id=workflow + ':step2', payload={
                'title': 'Follow up on recovered task', 'parent_resource_id': first['resource_id']})
            print('SCRIPTED next step:', ledger.post('/execute', json=request).json(), flush=True)
        else:
            from client_agent import run_agent
            run_agent(workflow, url)
        actions = ledger.get('/actions', params={'workflow_id': workflow}).json()['actions']
        assert len(actions) == 2, actions
        assert actions[0]['status'] == 'RECOVERED_SUCCESS', actions
        assert actions[1]['status'] == 'CONFIRMED_SUCCESS', actions
        tasks = []
        for step in (1, 2):
            matches = tracker.get('/tasks', params={'tag': f'{workflow}:step{step}'}).json()['tasks']
            assert len(matches) == 1, matches
            tasks.extend(matches)
        assert tasks[1]['payload']['parent_resource_id'] == tasks[0]['resource_id']
        for line in (run_dir / 'services.log').read_text().splitlines():
            if line.startswith('TRACKER:'):
                print(line, flush=True)
        print('VERIFY: step1 task count = 1; step2 task count = 1; parent ID matches. PASS', flush=True)
        print('LIMITATION: recovery requires conclusive lookup; unavailable evidence means AMBIGUOUS.', flush=True)
        evidence = {'mode': 'scripted' if args.scripted else 'live_llm', 'workflow_id': workflow,
                    'actions': actions, 'tracker_tasks': tasks, 'verified': True}
        (run_dir / 'verification.json').write_text(json.dumps(evidence, indent=2))
    print(f'Evidence: {run_dir}', flush=True)


if __name__ == '__main__':
    main()
