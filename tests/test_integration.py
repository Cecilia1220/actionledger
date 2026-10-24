"""Real HTTP + SQLite checks; no LLM/key needed."""
from concurrent.futures import ThreadPoolExecutor
import json
import sqlite3
import time
import httpx
import pytest
from demo import services
from common import AGENT_KEY


@pytest.fixture
def system(tmp_path):
    with services(tmp_path) as clients:
        yield (*clients, tmp_path)


def request(name='w:step1', **payload):
    return {'action_id': name, 'workflow_id': 'w', 'payload': payload or {'title': 'A'}}


def test_lost_ack_cached_and_hash_conflict(system):
    ledger, tracker, _, _ = system
    tracker.post('/faults', json={'mode': 'lost_ack'})
    result = ledger.post('/execute', json=request()).json()
    assert result['status'] == 'RECOVERED_SUCCESS'
    assert result['safe_to_retry'] is False
    assert ledger.post('/execute', json=request()).json() == result
    assert len(tracker.get('/tasks', params={'tag': 'w:step1'}).json()['tasks']) == 1
    assert ledger.post('/execute', json=request(title='different')).status_code == 409
    assert ledger.get('/status/w:step1').json() == result
    assert ledger.get('/actions', params={'workflow_id': 'w'}).json()['actions'] == [result]


def test_safe_retry_and_failed(system):
    ledger, tracker, _, _ = system
    tracker.post('/faults', json={'mode': 'before_execution'})
    assert ledger.post('/execute', json=request()).json()['status'] == 'SAFE_TO_RETRY'
    assert ledger.post('/execute', json=request()).json()['status'] == 'CONFIRMED_SUCCESS'
    tracker.post('/faults', json={'mode': 'rejected'})
    assert ledger.post('/execute', json=request('w:step2')).json()['status'] == 'FAILED'


def test_ambiguous_blocks_reexecution(system):
    ledger, tracker, _, _ = system
    tracker.post('/faults', json={'mode': 'lost_ack', 'lookup_available': False})
    for _ in range(2):
        result = ledger.post('/execute', json=request()).json()
        assert result['status'] == 'AMBIGUOUS' and result['safe_to_retry'] is False
    tracker.post('/faults', json={'mode': 'none', 'lookup_available': True})
    assert ledger.get('/status/w:step1').json()['status'] == 'RECOVERED_SUCCESS'
    assert len(tracker.get('/tasks', params={'tag': 'w:step1'}).json()['tasks']) == 1


def test_auth_allowlist_and_concurrent_calls(system):
    ledger, tracker, url, _ = system
    assert httpx.get(url + '/actions', params={'workflow_id': 'w'}).status_code == 401
    assert ledger.post('/execute', json={**request(), 'tool': 'email.send'}).status_code == 403
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: ledger.post('/execute', json=request()).json(), range(5)))
    assert len({r['resource_id'] for r in results}) == 1
    assert len(tracker.get('/tasks', params={'tag': 'w:step1'}).json()['tasks']) == 1


def test_restart_persistence_and_stale_execution(tmp_path):
    with services(tmp_path) as (ledger, tracker, _):
        result = ledger.post('/execute', json=request()).json()
    with sqlite3.connect(tmp_path / 'ledger.sqlite3') as db:
        db.execute("UPDATE actions SET state='EXECUTING', updated=?", (time.time()-30,))
    with services(tmp_path) as (ledger, tracker, _):
        recovered = ledger.get('/actions', params={'workflow_id': 'w'}).json()['actions'][0]
        assert recovered['status'] == 'RECOVERED_SUCCESS'
        assert recovered['resource_id'] == result['resource_id']
        assert len(tracker.get('/tasks', params={'tag': 'w:step1'}).json()['tasks']) == 1


def test_empty_uncertain_or_conflicting_evidence_stays_ambiguous(system):
    ledger, tracker, _, path = system
    ledger.post('/execute', json=request())
    with sqlite3.connect(path / 'tracker.sqlite3') as db:
        db.execute('DELETE FROM tasks')
    with sqlite3.connect(path / 'ledger.sqlite3') as db:
        db.execute("UPDATE actions SET state='UNKNOWN'")
    assert ledger.get('/status/w:step1').json()['status'] == 'AMBIGUOUS'
    tracker.post('/tasks', json={'tag': 'w:step1', 'payload': {'title': 'wrong'}})
    assert ledger.post('/execute', json=request()).json()['status'] == 'AMBIGUOUS'
