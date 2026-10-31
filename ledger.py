"""Single-process durable action ledger. Never blindly retry an uncertain write."""
import json
import os
import threading
import time
import httpx
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from common import AGENT_KEY, TRACKER_KEY, canonical, connect, digest

app = FastAPI(title='ActionLedger')
LOCK = threading.RLock()  # serialize execute + recovery in this single worker MVP
TRACKER_URL = os.getenv('TRACKER_URL', 'http://127.0.0.1:8001')
LEASE_SECONDS = 5
# HW7 change: how long a committed tracker write may stay invisible to lookup. 0 keeps the HW6
# rule (empty lookup after an uncertain write is AMBIGUOUS).
VISIBILITY_BOUND = float(os.getenv('VISIBILITY_BOUND_SECONDS', '0'))
with connect('ledger.sqlite3') as db:
    db.execute('''CREATE TABLE IF NOT EXISTS actions (
        action_id TEXT PRIMARY KEY, workflow_id TEXT, payload_hash TEXT,
        request TEXT, state TEXT, result TEXT, updated REAL)''')


class Action(BaseModel):
    action_id: str = Field(min_length=1, max_length=180)
    workflow_id: str = Field(min_length=1, max_length=120)
    tool: str = 'tracker.create_task'
    payload: dict


def auth(x_agent_key: str = Header(default='')):
    if x_agent_key != AGENT_KEY:
        raise HTTPException(401, 'Invalid agent key')


def tracker(method, path, **kwargs):
    # No HTTP retries: an uncertain create must go through verification.
    return httpx.request(method, TRACKER_URL + path, headers={'X-Tracker-Key': TRACKER_KEY},
                         timeout=3, **kwargs)


def read(action_id):
    with connect('ledger.sqlite3') as db:
        return db.execute('SELECT * FROM actions WHERE action_id=?', (action_id,)).fetchone()


def save(action, state, resource_id=None, evidence=None):
    result = {'action_id': action.action_id, 'status': state,
              'safe_to_retry': state == 'SAFE_TO_RETRY',
              'resource_id': resource_id, 'evidence': evidence or {}}
    with connect('ledger.sqlite3') as db:
        db.execute('UPDATE actions SET state=?,result=?,updated=? WHERE action_id=?',
                   (state, canonical(result), time.time(), action.action_id))
    print(f'LEDGER: {action.action_id} -> {state}', flush=True)
    return result


def recover(action, known_not_executed=False, since=None):
    # With a visibility bound, an empty lookup is re-checked until the bound has passed since the
    # write; a lookup that is still empty then is taken as evidence that the write never committed.
    deadline = (since or time.time()) + VISIBILITY_BOUND
    while True:
        try:
            response = tracker('GET', '/tasks', params={'tag': action.action_id})
            response.raise_for_status()
            tasks = response.json()['tasks']
            matches = [t for t in tasks if t['payload_hash'] == digest(action.payload)]
            evidence = {'lookup_tag': action.action_id, 'match_count': len(matches),
                        'task_count': len(tasks), 'tasks': tasks}
            if len(tasks) == len(matches) == 1:
                return save(action, 'RECOVERED_SUCCESS', matches[0]['resource_id'], evidence)
            if not tasks and known_not_executed:
                return save(action, 'SAFE_TO_RETRY', evidence=evidence)
            if not tasks and VISIBILITY_BOUND:
                if time.time() < deadline:
                    time.sleep(1)
                    continue
                evidence['reason'] = f'Lookup still empty {VISIBILITY_BOUND:g} s after the write'
                return save(action, 'SAFE_TO_RETRY', evidence=evidence)
            evidence['reason'] = 'No conclusive unique match; no automatic retry'
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            evidence = {'reason': 'Verification unavailable', 'error_type': type(exc).__name__}
        return save(action, 'AMBIGUOUS', evidence=evidence)


@app.get('/health')
def health():
    return {'ok': True}


@app.post('/execute', dependencies=[Depends(auth)])
def execute(action: Action):
    if action.tool != 'tracker.create_task':
        raise HTTPException(403, 'Tool not allowlisted')
    identity_hash = digest(action.model_dump(exclude={'action_id'}))
    with LOCK:
        row = read(action.action_id)
        if row:
            if row['payload_hash'] != identity_hash:
                raise HTTPException(409, 'action_id already bound to a different request')
            if row['state'] in ('CONFIRMED_SUCCESS', 'RECOVERED_SUCCESS', 'FAILED'):
                return json.loads(row['result'])
            if row['state'] != 'SAFE_TO_RETRY':
                return recover(action, since=row['updated'])
        else:
            with connect('ledger.sqlite3') as db:
                db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?,?)',
                           (action.action_id, action.workflow_id, identity_hash,
                            canonical(action.model_dump()), 'PENDING', None, time.time()))
        save(action, 'EXECUTING')  # durable before the external write
        sent = time.time()
        try:
            response = tracker('POST', '/tasks', json={'tag': action.action_id, 'payload': action.payload})
            if response.status_code in (400, 422):
                return save(action, 'FAILED', evidence={'http_status': response.status_code})
            if response.status_code == 503 and response.json().get('detail') == {'not_executed': True}:
                return recover(action, known_not_executed=True)
            response.raise_for_status()
            return save(action, 'CONFIRMED_SUCCESS', response.json()['resource_id'], response.json())
        except (httpx.HTTPError, ValueError, KeyError):
            save(action, 'UNKNOWN')
            return recover(action, since=sent)


@app.get('/status/{action_id}', dependencies=[Depends(auth)])
def status(action_id: str):
    with LOCK:
        row = read(action_id)
        if not row:
            raise HTTPException(404, 'Unknown action')
        if row['state'] in ('PENDING', 'EXECUTING', 'UNKNOWN', 'AMBIGUOUS'):
            if row['state'] in ('PENDING', 'EXECUTING') and time.time() - row['updated'] < LEASE_SECONDS:
                return json.loads(row['result']) if row['result'] else {'status': 'PENDING', 'safe_to_retry': False}
            return recover(Action.model_validate_json(row['request']), since=row['updated'])
        return json.loads(row['result'])


@app.get('/actions', dependencies=[Depends(auth)])
def actions(workflow_id: str):
    with connect('ledger.sqlite3') as db:
        ids = db.execute('SELECT action_id FROM actions WHERE workflow_id=? ORDER BY rowid',
                         (workflow_id,)).fetchall()
    return {'actions': [status(r['action_id']) for r in ids]}
