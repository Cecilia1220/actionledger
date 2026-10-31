"""Summarize benchmark runs: python -m bench.report results/phase1-opus [more dirs...]

Writes summary.md and cells.csv into the first directory and prints the markdown.
"""
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import statistics
import sys

ARMS = ['AL', 'B1', 'B0']


def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def load(dirs):
    return [json.loads(line) for d in dirs for line in (Path(d) / 'runs.jsonl').read_text().splitlines()]


def case_key(case_id):
    return (case_id[0], int(case_id[1:]))


def summarize(runs):
    arms = [a for a in ARMS if any(r['arm'] == a for r in runs)]
    lines = ['| Arm | Runs | Correct | Rate (95% CI) | Unsafe | False claim | No report | '
             'Model calls | Tokens in/out | USD/run | USD/correct | Median s |', '|' + '---|' * 12]
    for arm in arms:
        rs = [r for r in runs if r['arm'] == arm]
        k = sum(r['correct'] for r in rs)
        lo, hi = wilson(k, len(rs))
        outcomes = Counter(r['outcome'] for r in rs)
        usd = sum(r.get('cost_usd', 0) for r in rs)
        tokens_in = statistics.mean(r.get('input_tokens', 0) + r.get('cache_read', 0) + r.get('cache_write', 0) for r in rs)
        lines.append(f'| {arm} | {len(rs)} | {k} | {k / len(rs):.0%} ({lo:.0%}–{hi:.0%}) | {outcomes["UNSAFE"]} | '
                     f'{outcomes["FALSE_CLAIM"]} | {outcomes["NO_REPORT"] + outcomes["HARNESS_ERROR"]} | '
                     f'{statistics.mean(r.get("llm_calls", 0) for r in rs):.1f} | '
                     f'{tokens_in:,.0f} / {statistics.mean(r.get("output_tokens", 0) for r in rs):,.0f} | '
                     f'{usd / len(rs):.3f} | {usd / k if k else float("nan"):.3f} | '
                     f'{statistics.median(r.get("wall_seconds", 0) for r in rs):.1f} |')
    cells = defaultdict(list)
    for r in runs:
        cells[(r['case'], r['arm'])].append(r)
    cases = sorted({r['case'] for r in runs}, key=case_key)
    lines += ['', '| Case | Expect | ' + ' | '.join(arms) + ' |', '|' + '---|' * (len(arms) + 2)]
    rows = []
    for case in cases:
        expect = next(r['expect'] for r in runs if r['case'] == case)
        out = []
        for arm in arms:
            rs = cells[(case, arm)]
            k = sum(r['correct'] for r in rs)
            detail = ', '.join(f'{n} {o}' for o, n in Counter(r['outcome'] for r in rs).most_common())
            out.append(f'{k}/{len(rs)} ({detail})' if rs else '–')
            if rs:
                rows.append({'case': case, 'arm': arm, 'expect': expect, 'runs': len(rs), 'correct': k,
                             'outcomes': detail, 'unsafe': sum(r['outcome'] == 'UNSAFE' for r in rs),
                             'mean_usd': round(statistics.mean(r.get('cost_usd', 0) for r in rs), 4),
                             'median_seconds': statistics.median(r.get('wall_seconds', 0) for r in rs),
                             'mean_llm_calls': round(statistics.mean(r.get('llm_calls', 0) for r in rs), 2),
                             'mean_write_calls': round(statistics.mean(r.get('write_calls', 0) for r in rs), 2)})
        lines.append(f'| {case} | {expect} | ' + ' | '.join(out) + ' |')
    pass_all = {arm: sum(1 for case in cases if cells[(case, arm)]
                         and all(r['correct'] for r in cells[(case, arm)])) for arm in arms}
    lines += ['', 'Cases with every repetition correct: '
              + ', '.join(f'{arm} {pass_all[arm]}/{len(cases)}' for arm in arms)]
    return '\n'.join(lines), rows


def main():
    dirs = sys.argv[1:]
    runs = load(dirs)
    text, rows = summarize(runs)
    header = f'# Summary: {", ".join(dirs)}\n\nModels: {", ".join(sorted({r["model"] for r in runs}))}. ' \
             f'Total spend USD {sum(r.get("cost_usd", 0) for r in runs):.2f}.\n\n'
    (Path(dirs[0]) / 'summary.md').write_text(header + text + '\n')
    with (Path(dirs[0]) / 'cells.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(header + text)


if __name__ == '__main__':
    main()
