# Changelog

## 0.3.0 - unreleased

Renamed from `twinmemory-cli` to `@alexein/cli`, and `TWIN_MEMORY_API_KEY` / `TWIN_MEMORY_BASE_URL` to `ALEXEIN_API_KEY` / `ALEXEIN_API_URL`.

Run it as `npx @alexein/cli` (the command it installs is `alexein-cli`). 0.3.0 is the version every
Alexein package starts from.

- `init` writes a short `memory.ts` on `@alexein/sdk` instead of a ~300-line copy of the memory
  logic: the settings (`FAST`, `STRICT`, `MAX_CHARS`, `TIMEOUT`) and one configured
  `AlexeinMemory`, re-exporting what the graph or agent is built with. Its client is made on first
  use, so importing the file needs no key. Recall, remember, the prompt
  block and the tools come from `@alexein/sdk/langgraph` and `@alexein/sdk/openai-agents`, so they
  are fixed and improved by upgrading a dependency, not by regenerating a file.
- The wiring is `memory.recall`, `memory.remember`, `memory.prompt(state)` and
  `memory.tools({ write })` (`memory_search`, `memory_open`, `memory_add`, on the v2 API), with
  `MemoryAnnotation` / `MemoryState` / `MemoryContext` for LangGraph.js.
- `init` and `create` add `@alexein/sdk` to the project's dependencies, with the packages its
  integration needs: LangGraph.js 1.0 and LangChain core 1.0, or `@openai/agents` 0.21 and zod 4.
- The key and address are `ALEXEIN_API_KEY` and `ALEXEIN_API_URL`, in `.env`, the created
  projects and every message.
- `doctor` checks `@alexein/sdk` is declared and installed, says where `ALEXEIN_API_KEY` and
  `ALEXEIN_API_URL` come from (`.env` or the environment), and checks the key with `memory.me()`
  (`GET /v2/me`). A read-only key is called out when the project's code saves.

## 0.1.0 - unreleased

First release, for LangGraph.js and the OpenAI Agents SDK: `init`, `create` and `doctor`.
