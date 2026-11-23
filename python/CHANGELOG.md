# Changelog

## Unreleased

- `memory.user(id)` takes what the API takes since 2026-11-23: the id your app already has (a UUID, an email,
  `auth0|...`), up to 128 characters with no control character, no space at either end, ASCII only. Before:
  1 to 35 letters, digits, `.`, `_` and `-`.

## 0.3.3 - 2026-11-20

The same version as `@alexein/sdk`, which has the same changes.

- `add(text, id="diet")`: `id` is a keyword, as Add's other fields are, and names the one item added, so
  sending it again edits it. With several items it is a `ValueError`: give each its own `id`.
- `SearchResult.search_id`, and `user.feedback(result_or_search_id, "wrong" | "missing" | "ok", note=...)`
  to say how a search went.
- The API's other routes: `user.subject(name, limit=)`, `user.related(ref)`,
  `user.how_they_work(who=, surface=)`, `user.lessons(task)` and `user.refresh()`, answering `Subject`,
  `Related`, `Ways`, `Lessons` and `Refreshed`.
- `context()` keeps each memory on one line: an excerpt's text is its header, a blank line, then what was
  said, so its line breaks are made spaces. The memory itself keeps them.
- `AppUser` has `raw`, as every result does.

## 0.3.1 - 2026-11-17

- `QuotaExceededError`: a 402, when the organisation has used this month's events (on an add) or retrievals
  (on a search; every other read is free). Never
  retried, and not an outage, so a `fail_open` client raises it too. Carries `limit`, `used`, `included`,
  `resets_at` and `upgrade`. A 403 is also an organisation that is closed.
- An excerpt with no `roles` from `grep` or `latest` is `["other"]`: the API sends `roles` only when the
  person or an assistant spoke.

## 0.3.0 - 2026-11-04

The client is `alexein` now (`pip install alexein`, `import alexein`), at the API's own version, and speaks
its `/v2` API.

- Renamed from `twinmemory`. The key is read from `ALEXEIN_API_KEY` and the host from `ALEXEIN_API_URL`; every
  error is an `AlexeinError`; the logger is `alexein`; the `User-Agent` is `alexein-python/0.3.0`.
- The `/v2` API: an app user is named by `X-Alexein-User`, and every memory has a ref. Search answers
  `memories` in order (`Known`, `Fact`, `Excerpt`), `notes` and `answerable`; `open(ref)` reads one whole,
  where `read`, `ls` and `lineage` were; `summary()` replaces `overview()`; `forget` takes `refs`;
  `correct` takes a ref; `status` answers queued, stored, processed or unknown.
- New: `facts`, `items`, `item`, `open_items`, `sources`, `export`, `delete`, and `memory.users()`, with
  `iter_facts`, `iter_items`, `iter_export` and `iter_users` to follow every page; `add(redact=True)`.
- A 422 names each field it refused in `AlexeinError.errors`; every 5xx is a `ServiceUnavailableError`.
- A base URL given with a trailing `/` or `/v2` names the same host.
- Integrations, as extras: `alexein.langgraph` (`alexein[langgraph]`), `alexein.openai_agents`
  (`alexein[openai-agents]`) and `alexein.crewai` (`alexein[crewai]`), each offering a model `memory_search`,
  `memory_open` and `memory_add`. `import alexein` imports none of them.
- Every call sends an `X-Request-Id` of its own (`req_...`), kept across its retries, and every error
  carries it as `request_id` - even a 500 a proxy answered, or no answer at all - so it can be found in
  the console's request logs.

## 0.2.0 - unreleased

- `Memory(fail_open=True)`: an outage - memory unreachable, timing out, or answering 429 or 5xx after
  retries - answers `search` empty and skips `add`, with `failed=True` and a warning logged, instead of
  raising. A wrong key or request still raises.
- `outage` on every error: whether it means memory is unavailable.
- `Memory(integration=...)`: a word added to the `User-Agent`, counted in the request log.
- The default base URL is `https://api.alexein.ai`.

## 0.1.0 - unreleased

First release: `Memory` and `AsyncMemory`, typed results, one error class per failure, retries on 429 and 503
honouring `Retry-After`, and an `Idempotency-Key` on every add.
