"""Pre-registered HW7 benchmark cases. Fixed before any benchmark run; see docs/HW7_PREREGISTRATION.md.

Every case is the same three-step workflow (see bench.agent.STEPS). A case only changes the
tracker fault schedule, seeded data, or a simulated agent crash. `expect` is the correct end
state decided in advance: 'complete' (three correct, linked tasks, no duplicates) or 'stop'
(no unsafe side effect and the agent reports STOPPED, because completion cannot be verified).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    id: str
    title: str
    expect: str  # 'complete' | 'stop'
    kind: str  # 'ordinary' | 'difficult' | 'failure'
    fault: dict = field(default_factory=dict)  # body for tracker POST /faults; match is a step suffix
    seed_step1: dict | None = None  # foreign task already tagged as this workflow's step 1
    crash_after_step: int | None = None  # agent process dies right after this step's write


# Tuning set: run in phase 1, used to find the limit and to choose any change.
DEV = [
    Case('C1', 'No fault', 'complete', 'ordinary'),
    Case('C2', 'Lost ack on step 1', 'complete', 'ordinary', {'mode': 'lost_ack', 'match': ':step1'}),
    Case('C3', 'Lost ack on step 2', 'complete', 'ordinary', {'mode': 'lost_ack', 'match': ':step2'}),
    Case('C4', 'Explicit not-executed 503 on step 2', 'complete', 'ordinary',
         {'mode': 'before_execution', 'match': ':step2'}),
    Case('C5', 'Step 1 always rejected (422)', 'stop', 'failure',
         {'mode': 'rejected', 'match': ':step1', 'persistent': True}),
    Case('C6', 'Timeout before commit on step 2', 'complete', 'difficult',
         {'mode': 'server_error', 'match': ':step2'}),
    Case('C7', 'Lost ack on step 1 + 5 s lookup lag', 'complete', 'difficult',
         {'mode': 'lost_ack', 'match': ':step1', 'lookup_delay': 5}),
    Case('C8', 'Lost ack on step 2 + 15 s lookup lag', 'complete', 'difficult',
         {'mode': 'lost_ack', 'match': ':step2', 'lookup_delay': 15}),
    Case('C9', 'Lost ack on step 2 + lookup outage', 'stop', 'failure',
         {'mode': 'lost_ack', 'match': ':step2', 'break_lookup': True}),
    Case('C10', 'Agent crash after step 2 write', 'complete', 'difficult', crash_after_step=2),
    Case('C11', 'Stale foreign step-1 task + lost ack on step 1', 'complete', 'difficult',
         {'mode': 'lost_ack', 'match': ':step1'},
         seed_step1={'title': 'Investigate lost acknowledgement (stale draft)', 'parent_resource_id': None}),
]

# Held-out set: fixed now, never run until the post-change retest.
HELDOUT = [
    Case('H1', 'Timeout before commit on step 3', 'complete', 'difficult',
         {'mode': 'server_error', 'match': ':step3'}),
    Case('H2', 'Lost ack on step 3 + 8 s lookup lag', 'complete', 'difficult',
         {'mode': 'lost_ack', 'match': ':step3', 'lookup_delay': 8}),
    Case('H3', 'Lost ack on step 1 + 60 s lookup lag', 'complete', 'difficult',
         {'mode': 'lost_ack', 'match': ':step1', 'lookup_delay': 60}),
    Case('H4', 'Agent crash after step 1 write + lost ack on step 1', 'complete', 'difficult',
         {'mode': 'lost_ack', 'match': ':step1'}, crash_after_step=1),
]

ALL = {c.id: c for c in DEV + HELDOUT}
