# Changelog

## Unreleased

- `connect --remove` takes out what `connect` added: through each tool's own command, at the scope
  `connect` uses (Claude Code's and Copilot CLI's plugin or server, Codex's and Gemini CLI's server,
  Antigravity's plugin, Devin Desktop's server), and by taking the `alexein` entry out of Cursor's and
  VS Code's files, with a `.bak` copy kept. A server named anything but `alexein`, or added to
  Antigravity without its plugin, is left, with a line saying to take it out in the tool's settings.
  Memory and the tools' sign-ins are untouched.
- `doctor --json` and `connect --list --json` give the same as one JSON object, for CI and agents;
  the exit codes are unchanged.
- `--key -` reads the key from stdin, so it is in no shell's history.
- The command is also installed as `alexein`, beside `alexein-cli`. `npx @alexein/cli` is unchanged:
  both names run the same file, which npx runs whichever it picks.
- `alexein-cli` (Python) has `connect` too, tool for tool the same.

## 0.4.1 - 2026-11-20

- The key check names the key as the console does, by its organisation's and project's names (their ids
  when it has none), the same line `alexein-cli` prints. A personal key says it is one, and that each user
  id names a collection in one person's memory, not an app user.
- `connect` signs Claude Code in to the plugin's server, `plugin:alexein:alexein`. It ran
  `claude mcp login alexein`, which only names the server `--no-plugin` adds, so after the plugin
  went in, the sign-in failed with `No MCP server named "alexein"`.
- Antigravity's sign-in line says what agy itself says: `/plugin`, expand alexein-ai, Sign in.

## 0.4.0 - 2026-11-17

- `connect` adds Alexein AI's memory server to the AI tools on this computer: Claude Code, Cursor,
  VS Code, GitHub Copilot CLI, Codex, Gemini CLI, Antigravity and Devin Desktop. Each is told
  through its own command where it has one (`claude mcp add`, `code --add-mcp`, ...); Cursor's
  `mcp.json`, and Devin Desktop's file when its CLI is not installed, get the `alexein` entry alone,
  with a copy of the file kept. Claude Code, Copilot CLI and Antigravity get Alexein AI's plugin,
  which carries the guidance on when to search and save (`--no-plugin` for the server alone).
- The tools sign in to Alexein themselves, so no key is written. `--key` sends one in a header
  instead, for CI. `--only`, `--list`, `--dry-run` and `--force` as their names say; a tool that
  has Alexein already is left as it is.

## 0.3.1 - 2026-11-04

- Published through npm's trusted publishing from GitHub Actions, with no token: the provenance on npm is
  GitHub's alone. The CLI is the same as 0.3.0.

## 0.3.0 - 2026-11-04

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
