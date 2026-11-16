"""Cold-start runs: python -m usability.run --round r1 --scenarios s1,s2 --agents claude,codex --reps 2

Each run starts its own tracker, ledger and recording proxy, gives a fresh agent session an empty
directory holding only docs/AGENT_GUIDE.md plus the task text, and afterwards checks the tracker's
SQLite file. Evidence goes to usability/evidence/<round>/<run>/.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid
import httpx
from demo import ROOT, free_port, services
from usability.check import check, parse_report
from usability.tasks import SCENARIOS

GUIDE = ROOT / 'docs' / 'AGENT_GUIDE.md'
EVIDENCE = ROOT / 'usability' / 'evidence'
TIMEOUT = 480
MODELS = {'claude': 'claude-sonnet-5-5', 'codex': 'gpt-6-astra'}


def agent_command(agent, prompt, workdir, last_message):
    if agent == 'claude':  # Claude Code, headless, no user settings, memory, hooks or MCP servers
        return ['claude', '-p', prompt, '--bare', '--model', MODELS[agent], '--output-format', 'stream-json',
                '--verbose', '--allowedTools', 'Bash', 'Read', '--max-turns', '40', '--no-session-persistence']
    return ['codex', 'exec', '--json', '--skip-git-repo-check', '--ephemeral', '--ignore-user-config',
            '--ignore-rules', '-m', MODELS[agent], '-C', str(workdir), '-s', 'workspace-write',
            '-c', 'sandbox_workspace_write.network_access=true', '-o', str(last_message), prompt]


def run_agent(agent, prompt, out, name):
    """One fresh session in an empty directory that holds only the guide."""
    workdir = Path(tempfile.mkdtemp(prefix='al-agent-'))
    shutil.copy(GUIDE, workdir / 'AGENT_GUIDE.md')
    last_message = workdir.parent / f'{workdir.name}.last'
    env = {'HOME': os.environ['HOME'], 'PATH': os.environ['PATH']}
    if agent == 'claude':
        env['ANTHROPIC_API_KEY'] = os.environ['ANTHROPIC_API_KEY']
    started = time.time()
    try:
        done = subprocess.run(agent_command(agent, prompt, workdir, last_message), cwd=workdir, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT)
        stdout, exit_code = done.stdout, done.returncode
    except subprocess.TimeoutExpired as exc:
        stdout, exit_code = (exc.stdout or b'').decode(errors='replace'), 'timeout'
    events = [json.loads(line) for line in stdout.splitlines() if line.startswith('{')]
    commands, final, info = [], '', {}
    for e in events:
        if agent == 'claude':
            if e.get('type') == 'assistant':
                commands += [json.dumps(c['input']) for c in e['message']['content'] if c['type'] == 'tool_use']
            if e.get('type') == 'result':
                final = e.get('result') or ''
                info = {'turns': e.get('num_turns'), 'cost_usd': e.get('total_cost_usd')}
        else:
            item = e.get('item', {})
            if e.get('type') == 'item.completed' and item.get('type') == 'command_execution':
                commands.append(item.get('command', ''))
            if e.get('type') == 'turn.completed':
                info = {'usage': e.get('usage')}
    if agent == 'codex' and last_message.exists():
        final = last_message.read_text()
        last_message.unlink()
    (out / f'{name}.transcript.jsonl').write_text(stdout)
    shutil.rmtree(workdir, ignore_errors=True)
    return {'agent': agent, 'model': MODELS[agent], 'exit': exit_code, 'seconds': round(time.time() - started, 1),
            'tool_calls': len(commands), 'final_message': final, 'report': parse_report(final),
            'commands': commands, 'workdir': str(workdir), **info}


def one_run(round_name, scenario_id, agents, rep):
    scenario = SCENARIOS[scenario_id]
    used = (agents * 2)[:len(scenario['prompts'])]
    run_id = f'{scenario_id}-{"-".join(used)}-r{rep}'
    out = EVIDENCE / round_name / run_id
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    data = Path(tempfile.mkdtemp(prefix='al-data-'))
    key, incident = f'agent-{uuid.uuid4().hex[:10]}', f'inc-{uuid.uuid4().hex[:4]}'
    proxy_port, sessions = free_port(), []
    with services(data, AGENT_KEY=key) as (_, tracker, ledger_url):
        proxy = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'usability.proxy:app', '--host', '127.0.0.1', '--port',
             str(proxy_port), '--log-level', 'warning'], cwd=ROOT,
            env=dict(os.environ, UPSTREAM=ledger_url, REQUEST_LOG=str(out / 'requests.jsonl')))
        try:
            url = f'http://127.0.0.1:{proxy_port}'
            for _ in range(100):
                try:
                    httpx.get(url + '/health', timeout=.3)
                    break
                except httpx.HTTPError:
                    time.sleep(.1)
            (out / 'requests.jsonl').write_text('')  # drop the readiness probe
            if scenario['fault']:
                tracker.post('/faults', json=scenario['fault']).raise_for_status()
            for n, (agent, template) in enumerate(zip(used, scenario['prompts']), 1):
                prompt = template.format(url=url, key=key, inc=incident)
                (out / f'session{n}-{agent}.task.md').write_text(prompt)
                sessions.append(run_agent(agent, prompt, out, f'session{n}-{agent}'))
                sessions[-1]['requests_so_far'] = len((out / 'requests.jsonl').read_text().splitlines())
        finally:
            proxy.terminate()
            proxy.wait(timeout=5)
        tracker_port = str(tracker.base_url.port)
    db = sqlite3.connect(data / 'tracker.sqlite3')
    tasks = [{'resource_id': f'task_{i}', 'tag': tag, 'payload': json.loads(payload)}
             for i, tag, payload in db.execute('SELECT id, tag, payload FROM tasks ORDER BY id')]
    ledger_db = sqlite3.connect(data / 'ledger.sqlite3')
    actions = [{'action_id': a, 'workflow_id': w, 'state': s, 'request': json.loads(r)}
               for a, w, s, r in ledger_db.execute('SELECT action_id, workflow_id, state, request FROM actions ORDER BY rowid')]
    requests = [json.loads(line) for line in (out / 'requests.jsonl').read_text().splitlines()]
    commands = [c for s in sessions for c in s.pop('commands')]
    forbidden = [str(ROOT), f':{tracker_port}', 'github.com', 'git clone']
    result = check(scenario, tasks, requests, [s['report'] for s in sessions], commands, forbidden)
    summary = {'run': run_id, 'round': round_name, 'scenario': scenario_id, 'title': scenario['title'],
               'fault': scenario['fault'], 'incident': incident, **result,
               'requests': len(requests), 'sessions': sessions,
               'guide_sha256': hashlib.sha256(GUIDE.read_bytes()).hexdigest(),
               'commit': subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True,
                                        text=True).stdout.strip(),
               'versions': {a: subprocess.run([a, '--version'], capture_output=True, text=True).stdout.strip()
                            for a in sorted(set(used))}}
    (out / 'tracker_tasks.json').write_text(json.dumps(tasks, indent=1))
    (out / 'ledger_actions.json').write_text(json.dumps(actions, indent=1))
    (out / 'summary.json').write_text(json.dumps(summary, indent=1))
    shutil.copy(data / 'services.log', out / 'services.log')
    for path in out.iterdir():  # per-run key and local paths stay out of the committed evidence
        text = path.read_text().replace(key, '<agent-key>').replace(os.environ['HOME'], '~')
        for s in sessions:
            text = text.replace(s['workdir'], '<workdir>').replace(s['workdir'].replace('/var/', '/private/var/'), '<workdir>')
        path.write_text(text)
    shutil.rmtree(data, ignore_errors=True)
    failed = [name for name, ok in result['checks'].items() if not ok]
    print(f'{run_id}: {"USEFUL" if result["useful_result"] else "NOT USEFUL"} '
          f'tasks={len(tasks)} requests={len(requests)} failed={failed}', flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--round', required=True)
    parser.add_argument('--scenarios', default='s1,s2,s3,s4')
    parser.add_argument('--agents', default='claude,codex')
    parser.add_argument('--reps', type=int, default=2)
    parser.add_argument('--parallel', type=int, default=4)
    args = parser.parse_args()
    agents = args.agents.split(',')
    jobs = []
    for scenario_id in args.scenarios.split(','):
        for shift in range(len(agents)):  # each agent goes first once; s2's second session is the other one
            order = agents[shift:] + agents[:shift]
            jobs += [(args.round, scenario_id, order, rep) for rep in range(1, args.reps + 1)]
    with ThreadPoolExecutor(args.parallel) as pool:
        list(pool.map(lambda job: one_run(*job), jobs))


if __name__ == '__main__':
    main()
