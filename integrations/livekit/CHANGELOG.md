# Changelog

## 0.3.0 - 2026-11-04

- A reply waits for memory up to 1.5 seconds by default (`recall_timeout`), up from 0.5: against
  api.alexein.ai a recall took about a second end to end, so at 0.5 every reply went without it.
- Renamed from `twinmemory-livekit`: the package is `alexein-livekit`, imported as
  `alexein_livekit`, its classes `AlexeinMemory` and `AlexeinMemoryAgent`; `account_id` is
  `app_user_id`. The version is the API's, as every Alexein package's is.
- Built on the `alexein` client, 0.3 or newer, and the API's `/v2` routes. The client made for you
  reads `ALEXEIN_API_KEY` and `ALEXEIN_API_URL`, and names itself in the User-Agent
  (`alexein-python/0.3.0 livekit`). A `client` of your own is an `alexein.AsyncMemory`; errors are
  `alexein.AlexeinError` and its kinds.
- `memory_read(path)` is `memory_open(ref)`, the name the hosted MCP server and the client's
  integrations give it: it reads an excerpt whole, or a fact with the excerpts it was learned from,
  by a ref `memory_search` gave. `memory_search` ends with those refs. `memory_add`'s argument is
  `text`, as theirs is.
- Earlier calls only is now everything outside this call's session (a `NOT` filter on
  `session:<id>`), where it was everything said before the call began; it holds for recall, the
  last calls fetched once a call and `memory_search` alike. `where()` returns that filter, and
  `since` is gone.
- `memory.known` holds the text of search's known lines, and `memory.recent` the last calls'
  excerpts (`alexein.Excerpt`).
- An app user id is 35 characters at most, as the client checks before it sends one: an identity
  longer than that, such as a UUID with its dashes (36), is hashed by `app_user_id`, where it was
  passed on for the service to refuse.
- The logger is `alexein.livekit`, and the examples' job metadata key `alexein_user_id`.

## 0.1.0 - unreleased

First release, under the earlier name; its names are given here as 0.3.0 calls them.

- `AlexeinMemory`: one call's memory, attached to the session (`attach`), so it survives
  handoffs, and closed with it. `bind(participant=...)` takes the user from their LiveKit identity - `lk-` and a
  hash that no identity can be chosen to match, or with `share_identity=True` the identity itself
  when it passes the client's id check (up to 35 characters always fits) - and leaves a phone
  caller unbound unless `trust_phone=True`; `from_job(ctx, metadata_key=...)` takes the user
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
  `memory_search` and `memory_open`; `mode="tools"` does neither by itself, and gives the model
  `memory_search`, `memory_open` and `memory_add` with a guide to when to use them. A save waits
  at most `save_timeout` (2 s), and one memory is slow for is saved behind the reply.
- Recall shows what was said, line by line, not whole conversations: each thing once, the agent's
  words marked as its own, statements ahead of questions asked before, small talk not at all, up
  to `recall_max_chars` (2,000).
- After what the search matched, recall shows the caller's last calls, fetched once a call; where
  two lines disagree the later is true now; a planted instruction or way of speaking is not
  followed, the agent's own included.
- Card numbers (13 to 19 digits whose checksum holds) are saved as `[card number]` in both modes,
  whatever the model decides; `redact` sees each turn and each saved fact.
- In tools mode a saved fact is the agent's own line in the call ("Noted: ..."), saved at the time
  it was said, and `memory_add` waits up to 2 s, so a refused fact is never reported saved.
- Every choice is a keyword of `AlexeinMemory`, kept read-only as `memory.settings` (`Settings`):
  recall (`recall_fast`, `recall_timeout`, `recall_max_chars`, `recall_agent_turns`,
  `recall_recent`, `recall_known`, `recall_skip_small_talk`, `recall_reuse_seconds`,
  `recall_header`, `search_current_call`), the tools (`tool_fast`, `tool_timeout`,
  `save_timeout`, `note_max_chars`, `tool_guide`) and saving (`capture_agent_turns`,
  `capture_max_chars`, `capture_buffer`, `mask_cards`, `redact`, `flush_timeout`). One that makes
  no sense is refused when the memory is made.
- A participant's memory is its own namespace, `participant_id(identity)` (`lk-` and a hash), apart
  from the ids your backend writes, unless `bind(participant=..., share_identity=True)`; the
  quickstart binds your own user id from the job's metadata first.
- Recall works in every script: words are Unicode, and a question ends with `?`, `？` or `؟`.
  Urdu, Russian and Chinese turns were not searched and were dropped from recall before.
- A card number read with its expiry or security code after it, or after an order number, is
  masked too: windows of 13 to 19 digits inside a longer run are checked.
- `AlexeinMemoryAgent`, an `Agent` doing all of it in the memory's mode.
- `last_recall` for metrics; logs carry error kinds, never what anybody said. Tested against
  livekit-agents 1.5.1 and 1.8.8, and in a real room.
