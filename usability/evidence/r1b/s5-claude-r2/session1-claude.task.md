You are an operations agent. The file AGENT_GUIDE.md in the current directory documents a service called
ActionLedger. Read it first. Access for this job: base URL http://127.0.0.1:63775 , agent key <agent-key> .

Task: another agent started recording the follow-up plan for incident inc-ecf8 in the task tracker through
ActionLedger, using workflow id "inc-ecf8", and stopped partway. The full plan is:
1. "Investigate lost acknowledgement"
2. "Draft remediation plan", which depends on task 1
3. "Verify remediation", which depends on task 2

Finish the plan. Do not duplicate anything that already exists. Report all three tasks.

When you are finished or cannot continue, reply with only a JSON object, no other text:
{"complete": true or false, "tasks": [{"title": "...", "resource_id": "..." or null}], "not_done": ["anything you were asked to do but could not"], "notes": "one or two sentences"}
