# Cold-start results

Useful results out of runs, by the checks fixed in docs/HW9_COLD_START_PLAN.md. The agent named is the one that finished the job (agent B in handoffs).

| Scenario | Before: Claude Code | Before: Codex | After: Claude Code | After: Codex |
|---|---|---|---|---|
| S1 Lost acknowledgement on the first write | 2/2 | 2/2 | 2/2 | 2/2 |
| S2 Handoff between two agents | 2/2 | 2/2 | 2/2 | 2/2 |
| S3 Unverifiable outcome (boundary) | 2/2 | 2/2 | 2/2 | 2/2 |
| S4 Unsupported request | 2/2 | 2/2 | 2/2 | 2/2 |
| S5 Handoff from a client with opaque action ids | 2/2 | 2/2 | 2/2 | 2/2 |
| S6 Handoff, opaque ids, one unrelated task in the workflow | 2/4 | 3/4 | 4/4 | 4/4 |

**r1**: 16 runs, 20 sessions, 16 useful; commit 6963d48; 66 requests; median session 17.9 s; Claude Code spend USD 0.49.
Not useful: none.

**r1b**: 12 runs, 12 sessions, 9 useful; commit 0cbfce6, 172d84e; 50 requests; median session 30.6 s; Claude Code spend USD 0.54.
Not useful: s6-claude-r1 (report_complete_flag); s6-claude-r3 (task_count, titles_and_parent_chain, report_complete_flag, reported_ids_match_tracker); s6-codex-r1 (task_count, titles_and_parent_chain, report_complete_flag, reported_ids_match_tracker).

**r2**: 28 runs, 32 sessions, 28 useful; commit 542011c; 89 requests; median session 16.7 s; Claude Code spend USD 0.75.
Not useful: none.

**r2a**: 8 runs, 8 sessions, 8 useful; commit 6eea9e5; 16 requests; median session 15.3 s; Claude Code spend USD 0.20.
Not useful: none.
