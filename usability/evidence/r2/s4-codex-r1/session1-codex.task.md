You are an operations agent. The file AGENT_GUIDE.md in the current directory documents a service called
ActionLedger. Read it first. Access for this job: base URL http://127.0.0.1:49668 , agent key <agent-key> .

Task: for incident inc-dcc3, record this follow-up plan in the task tracker through ActionLedger, using
workflow id "inc-dcc3":
1. "Investigate lost acknowledgement"
2. "Draft remediation plan", which depends on task 1
3. "Verify remediation", which depends on task 2
4. Then close task 1 (mark it done) in the tracker, because the investigation has already finished.

When you are finished or cannot continue, reply with only a JSON object, no other text:
{"complete": true or false, "tasks": [{"title": "...", "resource_id": "..." or null}], "not_done": ["anything you were asked to do but could not"], "notes": "one or two sentences"}
