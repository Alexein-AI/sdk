# Changelog

## 0.2.0 - unreleased

- The `twinmemory` command, run as `uvx twinmemory`:
  - `init langgraph` writes a `memory.py` into a LangGraph project - `recall` and `remember` nodes,
    `memory_prompt`, and `MEMORY_TOOLS` / `MEMORY_WRITE_TOOLS` - as the developer's own code. It
    checks the project uses LangGraph 1.0 or newer and which graph the file is for before writing,
    adds what the file imports with the project's own tool, and sets up and checks the key, which
    can be skipped. Presets: `--async`, `--nodes-only`, `--tools-only`, `--fast`; `--dry-run`.
  - `create langgraph <name>`: a new uv project with a graph, a terminal chat and memory wired in.
  - `doctor`: whether a project is set up, each failure with its fix.
- `Memory(fail_open=True)`: an outage answers `search` empty and skips `add`, with `failed=True`
  and a warning logged, instead of raising. A wrong key or request still raises.
- `TwinMemoryError.outage`: whether an error means memory is unavailable.
- `Memory(integration=...)`: a word added to the `User-Agent`, counted in the request log.

## 0.1.0 - unreleased

First release.

- `Memory` and `AsyncMemory`, with `memory.user(id)` for each of your end users.
- `add`, `search` (with `fast` and `context()`), `history`, `latest`, `grep`, `read`, `ls`, `around`,
  `overview`, `forget`, `correct`, `versions`, `status`, `lineage`, and `memory.me()`.
- Typed results, one error class per failure, retries on 429 and 503 honouring `Retry-After`, and an
  `Idempotency-Key` on every add.
