You are an operations agent. The file AGENT_GUIDE.md in the current directory documents a service called
ActionLedger. Read it first. Access for this job: base URL http://127.0.0.1:62418 , agent key <agent-key> .

Task: incident inc-c482 has this follow-up plan, to be recorded in the task tracker through ActionLedger using
workflow id "inc-c482":
1. "Investigate lost acknowledgement"
2. "Draft remediation plan", which depends on task 1
3. "Verify remediation", which depends on task 2

Your shift ends early: record only tasks 1 and 2. Another agent will finish the plan later.

When you are finished or cannot continue, reply with only a JSON object, no other text:
{"complete": true or false, "tasks": [{"title": "...", "resource_id": "..." or null}], "not_done": ["anything you were asked to do but could not"], "notes": "one or two sentences"}
