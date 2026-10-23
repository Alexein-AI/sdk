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
- Two modes. `mode="auto"`, the default, recalls and saves on every turn, and lends the model
  `memory_search` and `memory_read`; `mode="tools"` does neither by itself, and gives the model
  `memory_search`, `memory_read` and `memory_add` with a guide to when to use them. `memory_add`
  answers at once and the fact is saved behind the reply.
- Recall shows what was said, line by line, not whole conversations: each thing once, the agent's
  words marked as its own, statements ahead of questions asked before, small talk not at all, up
  to `recall_max_chars` (2,000). 24 of 26 questions held the answer, against 21 for whole passages.
- After what the search matched, recall shows the caller's last calls, fetched once a call; where
  two lines disagree the later is true now; a planted instruction or way of speaking is not
  followed, the agent's own included.
- Card numbers (13 to 19 digits whose checksum holds) are saved as `[card number]` in both modes,
  whatever the model decides; `redact` sees each turn and each saved fact.
- In tools mode a saved fact is the agent's own line in the call ("Noted: ..."), so it keeps its
  time, and `memory_add` waits up to 2 s, so a refused fact is never reported saved.
- Every choice is a keyword of `TwinMemory`, kept read-only as `memory.settings` (`Settings`):
  recall (`recall_fast`, `recall_timeout`, `recall_max_chars`, `recall_agent_turns`,
  `recall_recent`, `recall_known`, `recall_skip_small_talk`, `recall_reuse_seconds`,
  `recall_header`, `search_current_call`), the tools (`tool_fast`, `tool_timeout`,
  `save_timeout`, `note_max_chars`, `tool_guide`) and saving (`capture_agent_turns`,
  `capture_max_chars`, `capture_buffer`, `mask_cards`, `redact`, `flush_timeout`). One that makes
  no sense is refused when the memory is made.
- `TwinMemoryAgent`, an `Agent` doing all of it in the memory's mode.
- `last_recall` for metrics; logs carry error kinds, never what anybody said. Tested against
  livekit-agents 1.5.1 and 1.8.8, in process, against a running twin memory, and in a real room.
