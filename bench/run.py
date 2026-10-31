"""Run benchmark cells (arm x case x repetition), each against fresh isolated services.

Example: python -m bench.run --phase phase1 --cases dev --arms AL,B1,B0 --reps 5
Appends one JSON line per run to results/<phase>/runs.jsonl and saves the trace beside it.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import uuid
import anthropic
from bench.agent import run_workflow, cost
from bench.cases import ALL, DEV, HELDOUT
from bench.grade import grade
from demo import services

RESULTS = Path(__file__).resolve().parent.parent / 'results'
WRITE_LOCK = threading.Lock()


def run_one(client, phase, model, arm, case, rep, ledger_env):
    wf = f'{case.id}-{arm}-r{rep}-{uuid.uuid4().hex[:6]}'
    out = RESULTS / phase
    data_dir = Path(tempfile.mkdtemp(prefix='bench-'))
    record = {'phase': phase, 'model': model, 'arm': arm, 'case': case.id, 'rep': rep, 'workflow_id': wf,
              'expect': case.expect, 'kind': case.kind, 'ledger_env': ledger_env}
    try:
        with services(data_dir, **ledger_env) as (ledger, tracker, ledger_url):
            seeded = set()
            if case.seed_step1:
                seeded_task = tracker.post('/tasks', json={'tag': f'{wf}:step1', 'payload': case.seed_step1}).json()
                seeded.add(int(seeded_task['resource_id'].split('_')[1]))
            if case.fault:
                tracker.post('/faults', json=case.fault).raise_for_status()
            started = time.perf_counter()
            events, usage, claim, end, sessions = run_workflow(
                client, model, arm, wf, str(tracker.base_url), ledger_url, case.crash_after_step)
            record.update(wall_seconds=round(time.perf_counter() - started, 2), sessions=sessions, end=end, **usage,
                          cost_usd=round(cost(model, usage), 5),
                          tool_calls=sum(1 for e in events if 'tool' in e and e['tool'] != 'finish'),
                          write_calls=sum(1 for e in events if e.get('tool') in ('create_task', 'execute_action')))
        record.update(grade(data_dir / 'tracker.sqlite3', wf, seeded, claim, end, case.expect))
        trace = {'record': record, 'events': events,
                 'services_log': (data_dir / 'services.log').read_text().splitlines()}
    except Exception as exc:  # keep the batch going; the failure is recorded, not hidden
        record.update(outcome='HARNESS_ERROR', correct=False, error=f'{type(exc).__name__}: {exc}')
        trace = {'record': record}
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
    with WRITE_LOCK:
        (out / 'traces').mkdir(parents=True, exist_ok=True)
        (out / 'traces' / f'{wf}.json').write_text(json.dumps(trace, indent=1, default=str))
        with (out / 'runs.jsonl').open('a') as f:
            f.write(json.dumps(record) + '\n')
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', required=True)
    parser.add_argument('--cases', default='dev', help='dev, heldout, or comma-separated case IDs')
    parser.add_argument('--arms', default='AL,B1,B0')
    parser.add_argument('--reps', type=int, default=5)
    parser.add_argument('--model', default='claude-opus-5-5')
    parser.add_argument('--parallel', type=int, default=6)
    parser.add_argument('--visibility-bound', type=float, default=None,
                        help='set VISIBILITY_BOUND_SECONDS for the ledger (the HW7 change)')
    args = parser.parse_args()
    if not os.getenv('ANTHROPIC_API_KEY'):
        sys.exit('Missing ANTHROPIC_API_KEY. Add it to .env.')
    cases = {'dev': DEV, 'heldout': HELDOUT}.get(args.cases) or [ALL[c] for c in args.cases.split(',')]
    ledger_env = {} if args.visibility_bound is None else {'VISIBILITY_BOUND_SECONDS': str(args.visibility_bound)}
    client = anthropic.Anthropic(max_retries=6)
    jobs = [(arm, case, rep) for rep in range(1, args.reps + 1) for case in cases for arm in args.arms.split(',')]
    print(f'{len(jobs)} runs, model={args.model}, ledger_env={ledger_env}', flush=True)
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = [pool.submit(run_one, client, args.phase, args.model, arm, case, rep, ledger_env)
                   for arm, case, rep in jobs]
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result()
            print(f'[{i}/{len(jobs)}] {r["case"]} {r["arm"]} r{r["rep"]}: {r["outcome"]}'
                  f' correct={r["correct"]} ${r.get("cost_usd", 0):.3f} {r.get("wall_seconds", "-")}s'
                  + (f' {r["error"]}' if 'error' in r else ''), flush=True)


if __name__ == '__main__':
    main()
