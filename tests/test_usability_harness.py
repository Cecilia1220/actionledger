"""The cold-start harness itself: a scripted stand-in for the agent, so no model or key is needed."""
import re
import httpx
import pytest
from usability import run
from usability.tasks import PLAN


def scripted(behaviour):
    def fake_agent(agent, prompt, out, name):
        url, key = re.search(r'base URL (\S+)', prompt).group(1), re.search(r'agent key (\S+)', prompt).group(1)
        incident = re.search(r'workflow id "([^"]+)"', prompt).group(1)
        report = behaviour(httpx.Client(base_url=url, headers={'X-Agent-Key': key}, timeout=20), incident)
        return {'agent': agent, 'model': 'scripted', 'exit': 0, 'seconds': 0, 'tool_calls': 0,
                'final_message': '', 'report': report, 'commands': [], 'workdir': '/nonexistent'}
    return fake_agent


def careful(client, incident):
    tasks, parent = [], None
    for n, title in enumerate(PLAN, 1):
        payload = {'title': title, **({'parent_resource_id': parent} if parent else {})}
        result = client.post('/execute', json={'action_id': f'{incident}:{n}', 'workflow_id': incident,
                                               'payload': payload}).json()
        if result['status'] not in ('CONFIRMED_SUCCESS', 'RECOVERED_SUCCESS'):
            return {'complete': False, 'tasks': tasks, 'not_done': PLAN[n - 1:]}
        parent = result['resource_id']
        tasks.append({'title': title, 'resource_id': parent})
    return {'complete': True, 'tasks': tasks, 'not_done': []}


def blind_retry(client, incident):
    for attempt in ('a', 'b'):  # a new action_id for the same write: the mistake the ledger exists to prevent
        client.post('/execute', json={'action_id': f'{incident}:1{attempt}', 'workflow_id': incident,
                                      'payload': {'title': PLAN[0]}})
    return {'complete': False, 'tasks': [], 'not_done': PLAN}


@pytest.mark.parametrize('scenario', ['s1', 's3'])
def test_careful_client_passes(scenario, tmp_path, monkeypatch):
    monkeypatch.setattr(run, 'EVIDENCE', tmp_path)
    monkeypatch.setattr(run, 'run_agent', scripted(careful))
    summary = run.one_run('test', scenario, ['claude'], 1)
    assert summary['useful_result'], summary['checks']
    assert '<agent-key>' in (tmp_path / 'test' / summary['run'] / 'session1-claude.task.md').read_text()


def test_blind_retry_is_caught(tmp_path, monkeypatch):
    monkeypatch.setattr(run, 'EVIDENCE', tmp_path)
    monkeypatch.setattr(run, 'run_agent', scripted(blind_retry))
    summary = run.one_run('test', 's3', ['claude'], 1)
    assert not summary['useful_result']
    assert not summary['checks']['task_count'] and not summary['checks']['no_duplicate_titles']


def finish_by_position(client, incident):
    """Takes the listed actions to be the plan's tasks in order: all a successor can do without content."""
    found = [a['resource_id'] for a in client.get('/actions', params={'workflow_id': incident}).json()['actions']]
    tasks = [{'title': title, 'resource_id': rid} for title, rid in zip(PLAN, found)]
    for n in range(len(found), len(PLAN)):
        made = client.post('/execute', json={'action_id': f'{incident}:{n + 1}', 'workflow_id': incident, 'payload': {
            'title': PLAN[n], 'parent_resource_id': tasks[-1]['resource_id']}}).json()
        tasks.append({'title': PLAN[n], 'resource_id': made['resource_id']})
    return {'complete': True, 'tasks': tasks, 'not_done': []}


@pytest.mark.parametrize('scenario,useful', [('s5', True), ('s6', False)])
def test_guessing_by_position_only_works_without_other_tasks(scenario, useful, tmp_path, monkeypatch):
    monkeypatch.setattr(run, 'EVIDENCE', tmp_path)
    monkeypatch.setattr(run, 'run_agent', scripted(finish_by_position))
    summary = run.one_run('test', scenario, ['claude'], 1)
    assert summary['useful_result'] is useful, summary['checks']
