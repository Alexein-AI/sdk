# Changelog

## 0.2.0 - unreleased

- `Memory(fail_open=True)`: an outage - memory unreachable, timing out, or answering 429 or 5xx
  after retries - answers `search` empty and skips `add`, with `failed=True` and a warning logged,
  instead of raising. A wrong key or request still raises.
- `TwinMemoryError.outage`: whether an error means memory is unavailable.
- `Memory(integration=...)`: a word added to the `User-Agent`, counted in the request log.
  `twinmemory-cli`'s generated LangGraph code sends `langgraph`.

## 0.1.0 - unreleased

First release.

- `Memory` and `AsyncMemory`, with `memory.user(id)` for each of your end users.
- `add`, `search` (with `fast` and `context()`), `history`, `latest`, `grep`, `read`, `ls`, `around`,
  `overview`, `forget`, `correct`, `versions`, `status`, `lineage`, and `memory.me()`.
- Typed results, one error class per failure, retries on 429 and 503 honouring `Retry-After`, and an
  `Idempotency-Key` on every add.
