# Changelog

## 0.1.0 - unreleased

First release.

- `TwinMemory`: one call's memory, attached to the session, so it survives handoffs. `from_job(ctx)`
  takes the user from the job's metadata; `bind(participant=...)` from their LiveKit identity,
  refusing a phone caller's unless `trust_sip=True`; turns said before `bind` wait for it.
- Recall before each reply, in `llm_node`: it keeps preemptive generation and covers typed turns.
  It searches earlier calls only, gets `recall_timeout` (0.5 s), skips small talk, searches a short
  answer with the question it answers, and puts what it found just before the user's words, inside
  `<memory>`, for that reply only.
- Capture of every committed turn through one ordered writer, with ids that make a retry replace
  rather than duplicate; turns wait out an outage and are saved within 5 s when the call ends.
- `TwinMemoryAgent`, an `Agent` doing both, with `search_memory` and `remember` tools.
- `last_recall` for metrics. Tested against livekit-agents 1.5.1 and 1.8.8.
