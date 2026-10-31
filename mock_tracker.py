"""Intentionally non-idempotent tracker. Fault controls are for localhost tests only."""
import json
import sqlite3
import time
from typing import Literal
from fastapi import FastAPI, Header, HTTPException, Depends
from pydantic import BaseModel
from common import TRACKER_KEY, connect, digest

app = FastAPI(title='Mock Tracker')
with connect('tracker.sqlite3') as db:
    db.execute('CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, tag TEXT, payload TEXT, created REAL)')
    try:  # databases created before HW7 lack the commit timestamp
        db.execute('ALTER TABLE tasks ADD COLUMN created REAL')
    except sqlite3.OperationalError:
        pass
faults = {'mode': 'none', 'lookup_available': True, 'match': '', 'persistent': False,
          'lookup_delay': 0.0, 'break_lookup': False}


def auth(x_tracker_key: str = Header(default='')):
    if x_tracker_key != TRACKER_KEY:
        raise HTTPException(401, 'Invalid tracker key')


class Task(BaseModel):
    tag: str
    payload: dict


class Fault(BaseModel):
    # lost_ack commits then times out; server_error times out without committing.
    # Both return the same 504 so a caller cannot tell them apart.
    mode: Literal['none', 'lost_ack', 'server_error', 'before_execution', 'rejected'] = 'none'
    lookup_available: bool = True
    match: str = ''  # apply mode only to creates whose tag contains this text
    persistent: bool = False  # keep mode armed after it fires
    lookup_delay: float = 0.0  # seconds before a committed task becomes visible to lookup
    break_lookup: bool = False  # lookup becomes unavailable once the fault fires


@app.get('/health')
def health():
    return {'ok': True}


@app.post('/faults', dependencies=[Depends(auth)])
def inject(fault: Fault):
    faults.update(fault.model_dump())
    return faults


@app.post('/tasks', dependencies=[Depends(auth)])
def create_task(task: Task):
    mode = faults['mode'] if faults['match'] in task.tag else 'none'
    if mode != 'none' and not faults['persistent']:
        faults['mode'] = 'none'  # one-shot injection
    if mode != 'none' and faults['break_lookup']:
        faults['lookup_available'] = False
    if mode == 'before_execution':
        raise HTTPException(503, {'not_executed': True})
    if mode == 'rejected':
        raise HTTPException(422, 'Task rejected before execution')
    if mode == 'server_error':
        print(f'TRACKER: injected TIMEOUT before commit (HTTP 504), tag={task.tag}', flush=True)
        raise HTTPException(504, 'Gateway timeout')
    with connect('tracker.sqlite3') as db:
        cursor = db.execute('INSERT INTO tasks(tag,payload,created) VALUES (?,?,?)',
                            (task.tag, json.dumps(task.payload), time.time()))
        resource_id = f'task_{cursor.lastrowid}'
    print(f'TRACKER: committed {resource_id}, tag={task.tag}', flush=True)
    if mode == 'lost_ack':
        print('TRACKER: injected LOST ACK after commit (HTTP 504)', flush=True)
        raise HTTPException(504, 'Gateway timeout')
    return {'resource_id': resource_id, 'tag': task.tag, 'payload_hash': digest(task.payload)}


@app.get('/tasks', dependencies=[Depends(auth)])
def find_by_tag(tag: str):
    if not faults['lookup_available']:
        raise HTTPException(503, 'Verification unavailable')
    visible_before = time.time() - faults['lookup_delay']
    with connect('tracker.sqlite3') as db:
        rows = db.execute('SELECT * FROM tasks WHERE tag=? AND (created IS NULL OR created<=?)',
                          (tag, visible_before)).fetchall()
    return {'tasks': [{'resource_id': f'task_{r["id"]}', 'tag': r['tag'],
                      'payload': json.loads(r['payload']),
                      'payload_hash': digest(json.loads(r['payload']))} for r in rows]}
