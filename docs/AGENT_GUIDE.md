# ActionLedger: guide for agents

This page is the whole interface. An agent that reads it should be able to use ActionLedger without reading
the source code.

## What it offers

ActionLedger is an HTTP service you call **instead of** calling a side-effecting tool directly. You send it a
write, it records the request durably, performs the write once, and tells you what happened. When the tool's
reply is lost (a timeout, a dropped acknowledgement), ActionLedger checks the tool's real state before
answering, so you do not have to guess whether to retry.

The tool behind this deployment is a task tracker that is **not idempotent**: two creates make two tasks.
ActionLedger currently supports one tool, `tracker.create_task`.

## Access

- Base URL: given to you by the operator, for example `http://127.0.0.1:8000`.
- Authentication: send the header `X-Agent-Key: <key>` on every call except `/health`. The operator gives you
  the key.
- All bodies are JSON (`Content-Type: application/json`).
- A machine-readable schema is at `GET /openapi.json`.
- Use a client timeout of at least 15 seconds. A call normally returns in milliseconds, but it can take a few
  seconds when ActionLedger has to verify an uncertain write.

## Operations

| Call | Purpose |
|---|---|
| `POST /execute` | Perform one write, or repeat a request you already sent |
| `GET /status/{action_id}` | Read the recorded outcome of one action; re-verifies it if it was uncertain |
| `GET /actions?workflow_id=...` | List the outcomes of every action in a workflow, oldest first |
| `GET /health` | Liveness check, no key needed; returns `{"ok": true}` |

### `POST /execute`: inputs

| Field | Type | Required | Meaning |
|---|---|---|---|
| `action_id` | string, 1–180 chars | yes | Your name for this one logical write. **You choose it.** The same `action_id` always means the same write |
| `workflow_id` | string, 1–120 chars | yes | Groups the actions of one job so they can be listed later |
| `tool` | string | no | Must be `tracker.create_task` (the default) |
| `payload` | JSON object | yes | The task to create, stored as given |

Payload fields for `tracker.create_task`:

| Field | Type | Meaning |
|---|---|---|
| `title` | string | The task title |
| `parent_resource_id` | string, optional | The `resource_id` of the task this one depends on, for example `"task_1"` |

Other payload fields are stored unchanged.

### Outputs

`POST /execute` and `GET /status/{action_id}` return HTTP 200 with:

| Field | Meaning |
|---|---|
| `action_id` | The id you sent |
| `status` | The outcome, see the next table |
| `resource_id` | The id of the created task, for example `"task_1"`; `null` if no task is known to exist |
| `safe_to_retry` | `true` only when `status` is `SAFE_TO_RETRY` |
| `evidence` | What ActionLedger saw: the tracker's reply, or the lookup result, or a `reason` |
| `request` | The request this action was recorded with: `{"workflow_id", "tool", "payload"}`. It tells you what the action is, even if you did not send it |

`GET /actions?workflow_id=...` returns `{"actions": [ ... ]}`, one such object per action. An unknown
workflow returns an empty list.

### What each status means and what to do

| `status` | Meaning | What you should do |
|---|---|---|
| `CONFIRMED_SUCCESS` | The tracker acknowledged the write | Continue. Use `resource_id` |
| `RECOVERED_SUCCESS` | The reply was lost, but ActionLedger found exactly one task with this action's tag and the same payload | Continue. Use `resource_id` exactly as for a confirmed write. Do not create the task again |
| `SAFE_TO_RETRY` | The write is known not to have happened | Send the identical request again, with the same `action_id` |
| `FAILED` | The tracker rejected the request before doing anything | Do not repeat it unchanged. Fix the request or report the failure |
| `AMBIGUOUS` | ActionLedger cannot tell whether the write happened (lookup is unavailable, or the result is not a single clean match) | **Stop this step. Do not send the write again under a new `action_id`**; that can create a duplicate. Report it. You may call `GET /status/{action_id}` later; it re-checks and can turn into `RECOVERED_SUCCESS` |
| `PENDING`, `EXECUTING`, `UNKNOWN` | The action is still in progress or has not been verified yet | Wait a few seconds and call `GET /status/{action_id}` |

### Choosing `action_id`

- Derive it from the job and the step, for example `inc-204:step-2`, so that the same step always gets the
  same id, including after you restart.
- Repeating a request with the same `action_id` and the same body is always safe: you get the recorded
  outcome and no second write.
- A new `action_id` is a new write. Never invent a fresh id to "try again".

### Resuming work

If you take over a workflow, or you restarted and lost your memory, call
`GET /actions?workflow_id=<id>` first. Each action in the list carries its `request`, so you can read what
it created (`request.payload.title`, `request.payload.parent_resource_id`) next to its `status` and
`resource_id`.

- Match existing actions to your plan by their `request.payload`. Do not go by position in the list or by the
  `action_id`: another client may name its actions differently, and a workflow can hold actions that are not
  part of your plan.
- Reuse what exists. Create only what is missing, under your own `action_id`.
- Leave actions that are not part of your plan alone. Never send a request under an `action_id` you did not
  choose in order to find out what it is.

## Errors

Errors return a JSON body `{"detail": ...}`.

| HTTP | `detail` | Meaning |
|---|---|---|
| 401 | `Invalid agent key` | Missing or wrong `X-Agent-Key` |
| 403 | `Tool not allowlisted` | `tool` is not `tracker.create_task` |
| 404 | `Unknown action` | `GET /status` for an `action_id` that was never sent |
| 409 | `action_id already bound to a different request` | You reused an `action_id` with a different `workflow_id`, `tool` or `payload` |
| 422 | a list of field errors | The body or query is missing a field or has the wrong type |

## Permissions and limits

- One agent key, one tool (`tracker.create_task`). ActionLedger cannot read, update, close or delete tasks.
- It only vouches for writes that went through it. Calling the tracker directly bypasses all protection.
- `AMBIGUOUS` is a real answer, not an error: this is not a universal exactly-once guarantee.
- One ledger process, local use only. No rate limit is enforced; calls are handled one at a time.

## Setup (operator)

Python 3.11+.

```bash
git clone https://github.com/Cecilia1220/actionledger.git
cd actionledger
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # sets AGENT_KEY=local-demo-agent for local use
python -m uvicorn mock_tracker:app --host 127.0.0.1 --port 8001 --workers 1 &
python -m uvicorn ledger:app --host 127.0.0.1 --port 8000 --workers 1 &
curl -s http://127.0.0.1:8000/health
```

## One small example

```bash
curl -s -X POST http://127.0.0.1:8000/execute \
  -H 'X-Agent-Key: local-demo-agent' -H 'Content-Type: application/json' \
  -d '{"action_id":"trip42:step1","workflow_id":"trip42","tool":"tracker.create_task","payload":{"title":"Investigate"}}'
```

```json
{"action_id": "trip42:step1", "status": "CONFIRMED_SUCCESS", "safe_to_retry": false,
 "resource_id": "task_1",
 "evidence": {"resource_id": "task_1", "tag": "trip42:step1", "payload_hash": "02e0809e…"},
 "request": {"workflow_id": "trip42", "tool": "tracker.create_task", "payload": {"title": "Investigate"}}}
```

A dependent task then uses that id:

```bash
curl -s -X POST http://127.0.0.1:8000/execute \
  -H 'X-Agent-Key: local-demo-agent' -H 'Content-Type: application/json' \
  -d '{"action_id":"trip42:step2","workflow_id":"trip42","tool":"tracker.create_task","payload":{"title":"Plan","parent_resource_id":"task_1"}}'
```
