# Changelog

## 0.1.0 - unreleased

First release: the JavaScript and TypeScript counterpart of the Python client, `twinmemory` 0.2.

- `Memory`, with `memory.user(id)` for each of your end users.
- `add`, `search` (with `fast` and `context()`), `history`, `latest`, `grep`, `read`, `ls`,
  `around`, `overview`, `forget`, `correct`, `versions`, `status`, `lineage`, and `memory.me()`.
- Typed results, one error class per failure, retries on 429 and 503 honouring `Retry-After`, a
  timeout per attempt, and an `Idempotency-Key` on every add.
- `failOpen`: an outage answers `search` empty and skips `add`, with `failed: true`, instead of
  throwing. `integration`: a word in the `User-Agent`.
- No dependencies; ESM and CommonJS.
