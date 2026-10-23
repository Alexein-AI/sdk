# Changelog

## 0.1.0 - unreleased

First release.

- `TwinMemory`: one call's memory, attached to the session (`attach`), so it survives handoffs, and
  closed with it. `bind(participant=...)` takes the user from their LiveKit identity - as it is when
  twin memory can use it as an id, else `lk-` and a hash that no identity can be chosen to match - and leaves a
  phone caller unbound unless `trust_phone=True`; `from_job(ctx, metadata_key=...)` takes the user
  from job metadata your backend wrote. Turns said before `bind` wait for it.
- Recall before each reply, in `llm_node`: it keeps preemptive generation and covers typed turns.
  It searches earlier calls only, gets `recall_timeout` (0.5 s) per reply however many model calls
  it makes, skips small talk, searches a short answer with the question it answers, and puts what
  it found just before the user's words, quoted inside `<memory>` and made inert, for that reply
  only. Nothing memory does or answers can stop a reply.
- Capture of every committed turn through one ordered writer, with ids that make a retry replace
  rather than duplicate; turns wait out an outage, a refused turn is set aside alone, a turn is cut
  at 8,000 characters, `redact` may change or drop any, and what is left is saved within 5 s when
  the session closes.
- `TwinMemoryAgent`, an `Agent` doing both, with `memory_search` and `memory_remember` tools.
- `last_recall` for metrics; logs carry error kinds, never what anybody said. Tested against
  livekit-agents 1.5.1 and 1.8.8, in process, against a running twin memory, and in a real room.
