# HW6 submission materials

Use the paragraph below **after the live `python demo.py` succeeds**. The scripted smoke test alone is not sufficient evidence of LLM use. Paste the paragraph into Canvas, and add the real unlisted video URL on a separate line. All three team members are listed.

## Exact Canvas paragraph

ActionLedger is agent-facing infrastructure for durable execution and recovery of side-effecting tool calls. Our HW6 MVP connects a real OpenAI tool-using agent to a SQLite-backed ActionLedger API and a non-idempotent mock task tracker. In the demo, the tracker creates a task but loses its acknowledgement; ActionLedger verifies the action tag and payload hash, returns RECOVERED_SUCCESS with the recovered task ID, and the agent uses that result to create a dependent follow-up task. Independent tracker queries verify exactly one task per step and a correct parent-task reference. The current limitation is that safe recovery requires trustworthy lookup evidence: unavailable or inconclusive verification returns AMBIGUOUS and blocks unsafe retries; this prototype does not guarantee exactly-once execution for arbitrary external tools. Team: Cecilia Zheng, Harry Hu, and Chris Chen.

## 60-second video / shot list

Prepare: activate `.venv`, set key, run once off camera, enlarge terminal font. Show no `.env` or credentials. Record your screen and narration. Capture a real run; model latency varies, so trim idle waiting if necessary without changing the sequence or hiding failures.

**0–8 seconds — Terminal, project name.**
“ActionLedger helps agents recover side-effecting tool calls when a tool performs an action but its reply is lost. Our team is Cecilia Zheng, Harry Hu, and Chris Chen.”

**8–18 seconds — Run `python demo.py`; show LIVE OpenAI label and first tool calls.**
“This is a real OpenAI tool-using agent. It reads durable workflow history, then asks ActionLedger to create a tracker task.”

**18–32 seconds — Highlight `RECOVERED_SUCCESS`, `safe_to_retry: false`, and resource ID.**
“The mock tracker commits the task, then injects a lost acknowledgement. ActionLedger checks the tag and payload hash and recovers task one instead of creating a duplicate.”

**32–44 seconds — Highlight the next model tool call and its `parent_resource_id`.**
“The model receives that result and uses the recovered task ID to create this dependent follow-up task. The returned result changes the agent’s next action.”

**44–54 seconds — Highlight `VERIFY ... PASS`.**
“Independent tracker queries confirm exactly one task for each step, and check that the follow-up references the original task.”

**54–60 seconds — Keep the limitation visible.**
“Our current limitation is lookup evidence. If verification is unavailable or inconclusive, ActionLedger returns ambiguous and stops unsafe retries.”

## Finish submission

1. Upload the recording to YouTube with visibility **Unlisted** (anyone with its link can view it; it is not a public search listing). Confirm playback from the link.
2. Canvas: paste the paragraph above and the real video URL. Include all team names.
3. Update the current class team spreadsheet with members, ActionLedger title/idea, and that video URL. The HW6 assignment's current spreadsheet link is the one to use; the older proposal points to a different sheet.
4. Each teammate can submit the same text and video link, as recommended by the assignment.

Video upload and class listing remain manual until the recording and URL exist. No grade is guaranteed; the live demonstration, result verification, limitation, and listing are all required by the rubric.
