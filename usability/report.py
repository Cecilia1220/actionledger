"""Summarize cold-start evidence: python -m usability.report  (writes usability/evidence/summary.md)"""
from collections import defaultdict
import json
from pathlib import Path
from usability.tasks import SCENARIOS

EVIDENCE = Path(__file__).parent / 'evidence'


def load(round_name):
    return [json.loads(p.read_text()) for p in sorted((EVIDENCE / round_name).glob('*/summary.json'))]


def cells(runs):
    """(scenario, agent that produced the final report) -> [useful, total]"""
    table = defaultdict(lambda: [0, 0])
    for run in runs:
        key = (run['scenario'], run['sessions'][-1]['agent'])
        table[key][0] += run['useful_result']
        table[key][1] += 1
    return table


def main():
    rounds = {name: load(name) for name in ('r1', 'r1b', 'r2', 'r2a') if (EVIDENCE / name).exists()}
    before, after = cells(rounds.get('r1', []) + rounds.get('r1b', [])), cells(rounds.get('r2', []))
    lines = ['# Cold-start results', '',
             'Useful results out of runs, by the checks fixed in docs/HW9_COLD_START_PLAN.md. '
             'The agent named is the one that finished the job (agent B in handoffs).', '',
             '| Scenario | Before: Claude Code | Before: Codex | After: Claude Code | After: Codex |',
             '|---|---|---|---|---|']
    for sid, scenario in SCENARIOS.items():
        row = [f'{sid.upper()} {scenario["title"]}']
        for table in (before, after):
            for agent in ('claude', 'codex'):
                useful, total = table.get((sid, agent), (0, 0))
                row.append(f'{useful}/{total}' if total else '–')
        lines.append('| ' + ' | '.join(row) + ' |')
    for name, runs in rounds.items():
        sessions = [s for run in runs for s in run['sessions']]
        failed = [f'{run["run"]} ({", ".join(k for k, ok in run["checks"].items() if not ok)})'
                  for run in runs if not run['useful_result']]
        seconds = sorted(s['seconds'] for s in sessions)
        lines += ['', f'**{name}**: {len(runs)} runs, {len(sessions)} sessions, '
                  f'{sum(run["useful_result"] for run in runs)} useful; service commit {runs[0]["commit"]}; '
                  f'{sum(run["requests"] for run in runs)} requests; median session '
                  f'{seconds[len(seconds) // 2]} s; Claude Code spend USD '
                  f'{sum(s.get("cost_usd") or 0 for s in sessions):.2f}.',
                  'Not useful: ' + ('; '.join(failed) if failed else 'none') + '.']
    (EVIDENCE / 'summary.md').write_text('\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
