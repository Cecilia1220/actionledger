# HW9 cold-start plan (written and committed before any agent run)

## Question

Can an agent that was not built or configured for ActionLedger use it for a real job from
[`docs/AGENT_GUIDE.md`](AGENT_GUIDE.md) alone?

The agents in HW6–HW8 do not answer this. Each ran inside a harness we wrote, with a prompt that taught it
ActionLedger's status contract. Here that knowledge has to come from the guide.

## Client agents

Two general-purpose coding agents, each started as a fresh headless session by `usability/run.py`:

| Agent | Version | Model | Isolation |
|---|---|---|---|
| Claude Code | 2.1.283 | claude-sonnet-5-5 | `--bare`: no user settings, memory, hooks, skills or MCP servers |
| Codex CLI | 0.154.0 | gpt-6-astra | `--ignore-user-config --ignore-rules --ephemeral` |

Neither is our own client. Both differ from the HW6 client (OpenAI Responses loop), the HW7 arms and the HW8
seller (our Claude Opus 5.5 tool loops).

This is a **self-run** test: our team starts the sessions. No other team's agent is involved.

## What a session is given

- An empty working directory that holds one file, `AGENT_GUIDE.md` (a copy of the guide at the tested commit).
- The task text in `usability/tasks.py`, which contains the base URL, a per-run agent key, the job, and the
  format of the final report. Nothing else: no call sequence, no ids to use, no expected answer, no mention of
  faults.
- A shell. The agent decides which calls to make.

The session does not get the repository, the tests, the benchmark, earlier transcripts, or the tracker's
address or key. Nobody sends it a message after it starts.

## Scenarios

The job in every scenario is to record a three-task follow-up plan for an incident, each task depending on
the previous one. The tracker's behaviour is set before the session starts.

| ID | Scenario | Tracker behaviour | Sessions |
|---|---|---|---|
| S1 | Lost acknowledgement on the first write | first create commits, then returns a timeout | one |
| S2 | Handoff: agent A records tasks 1–2, a different agent B must finish | none | A, then B (the other agent) |
| S3 | Unverifiable outcome (boundary) | first create commits and times out, and lookup stays down | one |
| S4 | Unsupported request: the job also asks to close task 1 | none | one |

S1 and S2 test the claim. S3 and S4 are the limitation tests: S3 is a failure ActionLedger cannot resolve,
S4 asks for something it does not offer.

## What counts as a useful result

Decided here, before the runs. Each run is checked by `usability/check.py` from three sources that do not
depend on the agent's own account: the tracker's SQLite file, the ledger's SQLite file, and a recording
pass-through (`usability/proxy.py`) that logs every request and response between the agent and the ledger.

A run is a **useful result** when all of these hold:

| Check | S1, S2 | S3 | S4 |
|---|---|---|---|
| Tasks in the tracker | exactly 3 | exactly 1 (the committed one) | exactly 3 |
| No two tasks with the same title | yes | yes | yes |
| Exact titles, and each task's `parent_resource_id` is the previous task's id | yes | first task only | yes |
| Final report parses and `complete` is | `true` | `false` | `false` |
| Every id in the report exists in the tracker under that title | yes | yes | yes |
| Report lists all three ids and they match the tracker | yes | n/a | n/a |
| Report's `not_done` is not empty | n/a | yes | yes |
| **Result use:** every parent id the agent sent had been returned to it by the ledger earlier | yes | yes | yes |
| Every tracker task was created through the ledger | yes | yes | yes |
| No shell command touched the repository, the tracker, or GitHub | yes | yes | yes |

For S1 the result-use check means the agent built task 2 on the id that came back with `RECOVERED_SUCCESS`.
For S2 it means agent B built task 3 on an id it read back from the ledger, since nobody told it the id.

## Separating project limits from test-setup problems

Every run that is not a useful result is read by hand and put in one of three groups, with the evidence:

- **Interface or documentation limitation:** the agent did something reasonable given the guide and the
  responses, and the job still failed or cost avoidable effort.
- **Agent error:** the guide and responses were sufficient and the agent still chose wrongly.
- **Test-setup problem:** the sandbox, CLI, proxy, timeout or checker got in the way. These runs are reported
  and repeated, and the harness fix is listed.

Friction that does not fail a run (extra calls, wrong first guesses, errors the agent had to work around) is
also recorded from the request log, because that is the evidence for what to improve.

## Runs

Round 1: each scenario twice with each agent going first, on the committed guide and service. That is 16
runs and 20 sessions (S2 has two sessions per run). Sessions are capped at 40 turns (Claude Code) and 8
minutes.

## Change and rerun rule

After round 1 we make **one** improvement to the interface or the guide, chosen from what round 1 showed. We
then rerun the affected scenarios with fresh sessions under the same task text, agents and checks, and add a
focused regression test. Round 1 evidence is kept as recorded. If round 1 shows nothing worth changing, we
say so and report the weakest point instead of inventing one.

## What we expect might go wrong

Written down so that it cannot be presented later as a discovery or hidden as a non-event:

- In S2, `GET /actions` returns outcomes and ids but not what each action was asked to create. Agent B may
  have to infer the earlier steps from agent A's choice of `action_id`s.
- In S3, an agent may treat `AMBIGUOUS` as an error to work around and send the write again under a new id.
- In S4, the only signal for an unsupported operation is `403 Tool not allowlisted`.

## Reproduce

```bash
pip install -r requirements.txt            # plus the claude and codex CLIs, signed in
python -m pytest -q tests/test_usability_harness.py   # harness check with a scripted client, no key
python -m usability.run --round r1         # 16 runs; needs ANTHROPIC_API_KEY in .env and a Codex login
```

## Addendum after round 1 (written before the boundary runs below)

Round 1 result: all 16 runs were useful results by the checks above (evidence in
`usability/evidence/r1/`). Nothing in the plan above was changed.

What round 1 showed about the handoff (S2). Every agent, in every run, named its actions
`<incident>:step-N`, the pattern the guide suggests. Agent B therefore saw `…:step-1` and `…:step-2` in
`GET /actions` and could tell what existed. It could not check it: Claude Code, as agent B, reported in both
of its runs that the ledger does not return titles or payloads, so it took the earlier tasks' titles from the
plan without verifying them. The handoff worked because both agents followed the same naming habit, not
because the interface told B what had been done.

That is the limitation we test next. A client is free to name actions any way it likes; our own HW8 seller
uses `town:{run}:{message_id}`. Two more scenarios, same task text as agent B in S2, same agents and checks:

| ID | Scenario | State before the session | Useful result |
|---|---|---|---|
| S5 | Handoff from a client with opaque action ids | an earlier client recorded plan tasks 1 and 2 through the ledger under random 12-character ids | exactly 3 tasks, correct chain, report ids match |
| S6 | As S5, plus one unrelated task in the same workflow | tasks recorded in order: plan task 1, "Notify incident channel", plan task 2 | exactly 4 tasks; "Verify remediation" depends on the real "Draft remediation plan"; report ids match |

The earlier client's work is real ledger and tracker state, created by the harness through `POST /execute`
before the session starts. S6 is built so that reading the action list by position gives the wrong answer;
`tests/test_usability_harness.py` shows a scripted client that guesses by position passing S5 and failing S6.

Runs: S5 and S6 twice with each agent on the round 1 guide and service (`--round r1b`). The one improvement
is chosen after these runs; S5, S6 and S2 are then rerun as round 2.

## Corrections and additions after the runs

Nothing above was edited. These are the places where what happened differs from what the plan says.

- **Isolation.** The plan says Claude Code's `--bare` loads no hooks or skills. The session records show no
  MCP servers and no memory files, but Claude Code's built-in skills and one user plugin (a terminal
  notification plugin) were loaded, and it ran in its `auto` permission mode. Codex ran shell commands through
  a login shell that sourced the user's profile. None of these carries project knowledge; across all
  transcripts the sessions only read the guide, called the service, hashed strings locally and wrote scratch
  files.
- **Checker.** The checks for S1–S4 were fixed before round 1. Adding S5 and S6 changed three lines of
  `usability/check.py` (seeded tasks count as written through the ledger; the plan-task count is capped at
  three) in the same commit as the addendum, before those runs. S1–S4 outcomes are unaffected.
- **More S6 runs than planned.** The addendum planned S6 twice per agent. Those four runs gave 2/4, so we ran
  four more on the unchanged service to see whether that was chance (3/4). All eight are reported. Round 2
  ran S6 four times per agent to match.
- **Round r2a, not planned.** The change added a field to the answers and three rules to the guide. To tell
  the two apart we reran S6 eight times on the changed service with the round 1 guide
  (`AGENT_GUIDE=<round 1 guide> python -m usability.run --round r2a --scenarios s6 --reps 4`).
- **Client permission mode.** In two of the three S6 failures, Claude Code's own auto-mode permission
  classifier refused a probing command the agent wanted to run. Those outcomes depend partly on that mode.
