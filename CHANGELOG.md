# Changelog

## 0.1.0 - unreleased

First release.

- `Memory` and `AsyncMemory`, with `memory.user(id)` for each of your end users.
- `add`, `search` (with `fast` and `context()`), `history`, `latest`, `grep`, `read`, `ls`, `around`,
  `overview`, `forget`, `correct`, `versions`, `status`, `lineage`, and `memory.me()`.
- Typed results, one error class per failure, retries on 429 and 503 honouring `Retry-After`, and an
  `Idempotency-Key` on every add.
