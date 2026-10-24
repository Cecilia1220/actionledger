# ActionLedger — MAS.665 HW6

A small agent-facing service for recovering side-effecting tool calls after an acknowledgement is lost. A real OpenAI tool-using client calls ActionLedger over HTTP; ActionLedger persists the request in SQLite, calls a deliberately non-idempotent mock tracker, verifies uncertain outcomes, and returns structured evidence. The model receives that result and uses the recovered task ID to create a dependent follow-up task.

Team: Cecilia Zheng, Harry Hu, Chris Chen.

## Quick start (Python 3.11+)

```bash
git clone https://github.com/Cecilia1220/actionledger.git
cd actionledger
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill `OPENAI_API_KEY` in `.env` using a text editor. Do not commit it. The local prepared checkout already has an empty `.env`; avoid overwriting a configured file. Set `OPENAI_MODEL` if your account uses another model supporting Responses function calling. A ChatGPT subscription alone does not supply an API key.

```bash
python demo.py
```

This one command starts both localhost services on available ports, injects one lost acknowledgement, runs the real agent, independently checks tracker state, saves evidence, and stops the services. Each run gets a fresh isolated database directory. No manual relaying of results is needed. It fails clearly if the key is absent; it never silently substitutes a fake agent.

Expect: `AGENT tool call` → `RECOVERED_SUCCESS` with `task_1` → a second model-generated tool call referencing `task_1` → `CONFIRMED_SUCCESS` → `VERIFY ... PASS`. The first step has exactly one task in this controlled demo. The model is bounded to eight calls and the demo checks the actual dependent resource, not only the model's summary.

### Check infrastructure without an API key

```bash
python demo.py --scripted
python -m pytest -q
```

`--scripted` is clearly labeled and only verifies infrastructure. **Record `python demo.py` with a real API key for HW6**, since a scripted check alone does not demonstrate a real agent using returned results.

## Run services individually

From the repository root, in two activated terminals:

```bash
python -m uvicorn mock_tracker:app --host 127.0.0.1 --port 8001 --workers 1
python -m uvicorn ledger:app --host 127.0.0.1 --port 8000 --workers 1
```

Optional: in a third activated terminal, run the client against these persistent services:

```bash
python -c 'from client_agent import run_agent; run_agent("manual-demo-1")'
```

Use a new workflow ID for a new workflow; reuse the same ID when resuming. The client first reads `/actions`. Services use `data/` by default, surviving restarts. `TRACKER_URL` and `DATA_DIR` can override defaults. Do not run multiple ledger workers.

## Minimal interface

Ledger headers: `X-Agent-Key` (value from `.env`, default local demo key).

- `POST /execute`: `{ "action_id": "trip42:step1", "workflow_id": "trip42", "tool": "tracker.create_task", "payload": { "title": "Investigate" } }`
- `GET /status/{action_id}`: return persisted outcome, reverify stale/uncertain work.
- `GET /actions?workflow_id=trip42`: discover prior work after client restart.

Responses include `status`, `resource_id`, `safe_to_retry`, and `evidence`.

- `CONFIRMED_SUCCESS`: write acknowledged; continue.
- `RECOVERED_SUCCESS`: exactly one tagged task with matching payload hash found; continue using its ID.
- `SAFE_TO_RETRY`: tracker explicitly guaranteed no execution and lookup is empty; repeat the identical request/ID.
- `FAILED`: known validation rejection before execution; replan.
- `AMBIGUOUS`: lookup unavailable, empty after an uncertain write, multiple tasks, or hash mismatch; stop/escalate, never blindly retry. A later status call may recover when evidence returns.
- `PENDING`, `EXECUTING`, `UNKNOWN`: durable intermediate states. Stale work is verified after a five-second lease on a status read. Repeated execute calls also verify uncertain work.

ID reuse with a different workflow/tool/payload returns HTTP 409. The request identity is hashed using canonical JSON and SHA-256. The tracker stores no idempotency key constraint: repeated direct creates really can duplicate tasks. The ledger verifies both the action tag and payload hash. Ledger auth permits a single configured demo agent and one allowlisted tool; tracker auth uses its own simulated service credential.

Tracker: `POST /tasks` creates a task; `GET /tasks?tag=...` looks up evidence. Local test-only `POST /faults` accepts `mode` (`none`, `lost_ack`, `before_execution`, `rejected`) and `lookup_available`. `lost_ack` commits the real SQLite write and then returns HTTP 504 instead of the success acknowledgement. It models lost acknowledgement rather than randomly delaying network packets. Fault mode is one-shot; lookup availability lasts until changed.

## Structure

```text
common.py                 configuration, canonical hashing, SQLite connection
mock_tracker.py           non-idempotent tracker + fault injector
ledger.py                 durable execution/recovery REST API
client_agent.py            real OpenAI Responses tool loop
demo.py                    isolated end-to-end runner + independent assertions
tests/test_integration.py  actual HTTP/SQLite failure, concurrency, restart tests
docs/HW6_SUBMISSION.md     exact Canvas paragraph and 60-second shot list
docs/TEAM_HANDOFF.md       group-chat draft and next-owner workflow
.env.example              empty model key + local-only demo credentials
requirements.txt          direct dependencies
requirements-lock.txt     versions used for local validation
```

Evidence is local under `data/demo-*/verification.json` and `services.log`; agent tool transcripts are `data/demo-*-agent.json`. These are ignored by git. A demo's SQLite files remain available for inspection. Check the `mode` field when distinguishing infrastructure evidence from a live LLM run.

## Scope and limitations

This HW6 slice uses two dependent steps rather than the proposal's later five-step benchmark. No MCP, graphical UI, hosted deployment, real tracker integration, or HW7 baselines are included. The agent is an SDK client, not a new framework. Function calling follows the [official OpenAI guide](https://developers.openai.com/api/docs/guides/function-calling).

Recovery depends on trustworthy lookup. This mock provides synchronous, immediately visible SQLite writes and stable tags. Arbitrary external services may have delayed visibility or still-running requests, so an empty lookup after an unknown outcome stays AMBIGUOUS. This is **not a universal exactly-once guarantee**. Multiple ledger processes, multi-tenant ownership/auth, high availability, transactional coordination with an external tracker, background lease sweeping, and automatic human escalation are out of scope. Single-worker locking protects concurrent calls in this MVP; it does not provide a distributed lock. Mock fault controls are local test facilities. Bind both services to localhost only.

## Team workflow

Start new work from current `main`, create your own feature branch, run checks, and merge only after it works:

```bash
git switch main
git pull --ff-only origin main
git switch -c feature/hw7-benchmark
# make changes
python -m pytest -q
python demo.py
git add <specific-files>
git commit -m "Add HW7 benchmark"
git push -u origin feature/hw7-benchmark
```

Open a GitHub pull request into `main`, review the diff, merge, then everyone pulls `main`. Each person supplies their own `.env`. Private repository access must be granted to teammates and graders if they need to clone it.
