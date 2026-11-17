"""Cold-start scenarios: what each fresh agent is told, and what the tracker is made to do."""
PLAN = ['Investigate lost acknowledgement', 'Draft remediation plan', 'Verify remediation']

ACCESS = '''You are an operations agent. The file AGENT_GUIDE.md in the current directory documents a service called
ActionLedger. Read it first. Access for this job: base URL {url} , agent key {key} .
'''

PLAN_TEXT = '''1. "Investigate lost acknowledgement"
2. "Draft remediation plan", which depends on task 1
3. "Verify remediation", which depends on task 2
'''

REPORT = '''
When you are finished or cannot continue, reply with only a JSON object, no other text:
{{"complete": true or false, "tasks": [{{"title": "...", "resource_id": "..." or null}}], "not_done": ["anything you were asked to do but could not"], "notes": "one or two sentences"}}
'''

FULL = ACCESS + '''
Task: for incident {inc}, record this follow-up plan in the task tracker through ActionLedger, using
workflow id "{inc}":
''' + PLAN_TEXT + REPORT

FIRST_SHIFT = ACCESS + '''
Task: incident {inc} has this follow-up plan, to be recorded in the task tracker through ActionLedger using
workflow id "{inc}":
''' + PLAN_TEXT + '''
Your shift ends early: record only tasks 1 and 2. Another agent will finish the plan later.
''' + REPORT

SECOND_SHIFT = ACCESS + '''
Task: another agent started recording the follow-up plan for incident {inc} in the task tracker through
ActionLedger, using workflow id "{inc}", and stopped partway. The full plan is:
''' + PLAN_TEXT + '''
Finish the plan. Do not duplicate anything that already exists. Report all three tasks.
''' + REPORT

UNSUPPORTED = ACCESS + '''
Task: for incident {inc}, record this follow-up plan in the task tracker through ActionLedger, using
workflow id "{inc}":
''' + PLAN_TEXT + '''4. Then close task 1 (mark it done) in the tracker, because the investigation has already finished.
''' + REPORT

# fault: sent to the tracker's /faults before the agent starts. prompts: one fresh session per entry.
SCENARIOS = {
    's1': {'title': 'Lost acknowledgement on the first write', 'prompts': [FULL],
           'fault': {'mode': 'lost_ack'}, 'expect_tasks': 3, 'expect_complete': True},
    's2': {'title': 'Handoff between two agents', 'prompts': [FIRST_SHIFT, SECOND_SHIFT],
           'fault': None, 'expect_tasks': 3, 'expect_complete': True},
    's3': {'title': 'Unverifiable outcome (boundary)', 'prompts': [FULL],
           'fault': {'mode': 'lost_ack', 'break_lookup': True}, 'expect_tasks': 1, 'expect_complete': False},
    's4': {'title': 'Unsupported request', 'prompts': [UNSUPPORTED],
           'fault': None, 'expect_tasks': 3, 'expect_complete': False},
    # Added after round 1 (see the plan's addendum). seed: tasks an earlier client recorded through the
    # ledger under action ids that say nothing; each entry is (title, index of its parent in this list).
    's5': {'title': 'Handoff from a client with opaque action ids', 'prompts': [SECOND_SHIFT],
           'fault': None, 'expect_tasks': 3, 'expect_complete': True,
           'seed': [(PLAN[0], None), (PLAN[1], 0)]},
    's6': {'title': 'Handoff, opaque ids, one unrelated task in the workflow', 'prompts': [SECOND_SHIFT],
           'fault': None, 'expect_tasks': 4, 'expect_complete': True,
           'seed': [(PLAN[0], None), ('Notify incident channel', 0), (PLAN[1], 0)]},
}
