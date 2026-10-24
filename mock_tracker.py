"""Intentionally non-idempotent tracker. Fault controls are for localhost tests only."""
import json
from typing import Literal
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel
from common import TRACKER_KEY, connect, digest

app = FastAPI(title='Mock Tracker')
with connect('tracker.sqlite3') as db:
    db.execute('CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, tag TEXT, payload TEXT)')
faults = {'mode': 'none', 'lookup_available': True}


def auth(x_tracker_key: str = Header(default='')):
    if x_tracker_key != TRACKER_KEY:
        raise HTTPException(401, 'Invalid tracker key')


class Task(BaseModel):
    tag: str
    payload: dict


class Fault(BaseModel):
    mode: Literal['none', 'lost_ack', 'before_execution', 'rejected'] = 'none'
    lookup_available: bool = True


@app.get('/health')
def health():
    return {'ok': True}


@app.post('/faults', dependencies=[Depends(auth)])
def inject(fault: Fault):
    faults.update(fault.model_dump())
    return faults


@app.post('/tasks', dependencies=[Depends(auth)])
def create_task(task: Task):
    mode = faults['mode']
    faults['mode'] = 'none'  # one-shot injection
    if mode == 'before_execution':
        raise HTTPException(503, {'not_executed': True})
    if mode == 'rejected':
        raise HTTPException(422, 'Task rejected before execution')
    with connect('tracker.sqlite3') as db:
        cursor = db.execute('INSERT INTO tasks(tag,payload) VALUES (?,?)',
                            (task.tag, json.dumps(task.payload)))
        resource_id = f'task_{cursor.lastrowid}'
    print(f'TRACKER: committed {resource_id}, tag={task.tag}', flush=True)
    if mode == 'lost_ack':
        print('TRACKER: injected LOST ACK after commit (HTTP 504)', flush=True)
        raise HTTPException(504, 'Acknowledgement lost after commit')
    return {'resource_id': resource_id, 'tag': task.tag, 'payload_hash': digest(task.payload)}


@app.get('/tasks', dependencies=[Depends(auth)])
def find_by_tag(tag: str):
    if not faults['lookup_available']:
        raise HTTPException(503, 'Verification unavailable')
    with connect('tracker.sqlite3') as db:
        rows = db.execute('SELECT * FROM tasks WHERE tag=?', (tag,)).fetchall()
    return {'tasks': [{'resource_id': f'task_{r["id"]}', 'tag': r['tag'],
                      'payload': json.loads(r['payload']),
                      'payload_hash': digest(json.loads(r['payload']))} for r in rows]}
