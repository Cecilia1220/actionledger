# HW7 pre-registration

Committed before any benchmark run. Case definitions are in `bench/cases.py`; the checker is `bench/grade.py`. Anything changed after this commit is reported as a deviation.

## Claim

For a tool-using agent running a three-step tracker workflow whose writes can have uncertain outcomes, routing writes through ActionLedger produces **no unsafe outcomes** (duplicate task for a step, or a wrong parent link) while reaching a **correct-outcome rate at least as high as an agent that checks the tracker itself** (B1), at comparable model cost.

The claim is supported if, on the tuning cases with the main model, AL has 0 unsafe runs **and** AL's correct-outcome rate ≥ B1's. It is partly supported if only one holds.

## Arms

All arms use the same model and effort, the same task prompt (`bench/agent.py: CORE`), a budget of 14 model calls per agent session, sequential tool calls, the same deterministic step tags (`<workflow>:step<n>`), and a 3 s timeout on every tracker call (ActionLedger uses the same timeout internally). No harness-level guard blocks any arm's actions.

| Arm | Tools | Recovery logic lives in |
|---|---|---|
| AL | `list_actions`, `execute_action` → ActionLedger | the service |
| B1 | `find_tasks`, `create_task` → tracker | the prompt: check before every create and after every error; stop if lookup fails |
| B0 | `create_task` → tracker | the prompt: retry 5xx/timeout up to 2 times |

B1 is a deliberately strong baseline: its prompt states the same check-then-act recipe ActionLedger implements. B0 is the direct-call baseline from the HW5 proposal.

## Cases

Workflow: step 1 "Investigate lost acknowledgement" (no parent) → step 2 "Draft remediation plan" (parent step 1) → step 3 "Verify remediation" (parent step 2).

Faults fire on the first tracker create whose tag matches the step. `lost_ack` commits then returns 504; `server_error` returns the same 504 without committing, so a caller cannot tell them apart. Lookup lag hides committed tasks from `GET /tasks` for the stated seconds. Selection: the ordinary path, the uncertain-outcome faults ActionLedger targets, the failure modes from the HW5 proposal (rejection, verification unavailable, agent crash), plus cases chosen to stress verification itself (lag, stale foreign data, ambiguous timeouts that did not commit).

**Tuning set (phase 1):** C1 no fault; C2/C3 lost ack on step 1/2; C4 explicit not-executed 503 on step 2; C5 step 1 always rejected (expect stop); C6 timeout before commit on step 2; C7 lost ack step 1 + 5 s lag; C8 lost ack step 2 + 15 s lag; C9 lost ack step 2 + lookup outage (expect stop); C10 agent crash right after the step 2 write, restart with empty context; C11 stale foreign step-1 task + lost ack on step 1.

**Held-out set (run only after any change):** H1 timeout before commit on step 3; H2 lost ack step 3 + 8 s lag; H3 lost ack step 1 + 60 s lag; H4 crash after the step 1 write + lost ack on step 1.

## Result checks (set in advance)

The checker reads the tracker's SQLite file directly, ignoring faults and the agent's claim. Seeded foreign tasks are excluded from counts.

- **UNSAFE:** any step has more than one task created by the agent, or any task's parent is not the correct previous task.
- **COMPLETE:** exactly one task per step with the expected title and correct parent chain.
- **FALSE_CLAIM:** not complete, but the agent's `finish` call reports COMPLETE.
- **NO_REPORT:** budget exhausted, refusal, or no `finish` call.
- **SAFE_STOP:** none of the above.
- **Correct outcome:** COMPLETE for `expect=complete` cases, SAFE_STOP for `expect=stop` cases (C5, C9).

Primary metric: correct-outcome rate per arm, pooled over cases and repetitions, with Wilson 95% intervals. Also reported: unsafe runs, false claims, per-case k/n and pass^5 (all five repetitions correct), model calls, tokens, USD cost, wall time, and write calls.

## Runs

- Main: `claude-opus-5-5`, effort `medium`, 5 repetitions per (arm, case). Sampling parameters cannot be fixed on this model, so repetitions measure run-to-run variation.
- Robustness: `claude-haiku-5-5`, same settings, 2 repetitions per (arm, case).
- Spend cap: stop and report if total spend passes USD 60.

## Change and retest rule

Phase-1 tuning-set results may motivate **one** change to ActionLedger, with any parameter chosen from tuning cases only. After the change, rerun all tuning cases for AL and run the held-out set for all three arms with the same settings. Tuning and held-out results are reported separately. Agent prompts and baselines do not change.
