# Changelog

## Unreleased

- `connect` adds Alexein AI's memory server to the AI tools on this computer - Claude Code, Cursor,
  VS Code, GitHub Copilot CLI, Codex, Gemini CLI, Antigravity and Devin Desktop - as
  `@alexein/cli connect` does, tool for tool, so it needs no Node. `--only`, `--no-plugin`,
  `--list`, `--key`, `--force`, `--dry-run` and `--yes` as there.
- `connect --remove` takes out what `connect` added: through each tool's own command, at the scope
  `connect` uses (Claude Code's and Copilot CLI's plugin or server, Codex's and Gemini CLI's server,
  Antigravity's plugin, Devin Desktop's server), and by taking the `alexein` entry out of Cursor's and
  VS Code's files, with a `.bak` copy kept. A server named anything but `alexein`, or added to
  Antigravity without its plugin, is left, with a line saying to take it out in the tool's settings.
  Memory and the tools' sign-ins are untouched.
- `doctor --json` and `connect --list --json` give the same as one JSON object, for CI and agents;
  the exit codes are unchanged.
- `--key -` reads the key from stdin, so it is in no shell's history.
- The command is also installed as `alexein`, beside `alexein-cli`; `uvx alexein-cli` is unchanged.

## 0.3.1 - 2026-11-20

- The key check says when the key is a personal key, and that each user id names a collection in one
  person's memory, not an app user - the same line `@alexein/cli` prints.

## 0.3.0 - 2026-11-04

Renamed from `twinmemory-cli`: the package is `alexein-cli` (`uvx alexein-cli ...`), the module
`alexein_cli`. The version follows the API's, as every Alexein package's does.

- `init langgraph | openai-agents | crewai` writes a short `memory.py` the developer owns: the
  settings (`FAST`, `STRICT`, `MAX_CHARS`, `TIMEOUT`), one configured `AlexeinMemory`, and the
  names the graph, agent or crew uses - everything else imported from the `alexein` client's
  `alexein.langgraph`, `alexein.openai_agents` and `alexein.crewai`. Importing it needs no key.
  It adds `alexein[<framework>]>=0.3` to the project, with the project's own tool, where the
  project does not depend on it already.
- One file serves nodes and tools, sync and async: `--async`, `--nodes-only` and `--tools-only`
  are gone. `--fast` stays.
- LangGraph 1.2 or newer is needed (its runtime carries the thread what is saved belongs to);
  the OpenAI Agents SDK 0.24 or newer.
- `create langgraph | openai-agents | crewai <name>` makes the same projects as before, on the
  thin file.
- `doctor` checks `ALEXEIN_API_KEY` and `ALEXEIN_API_URL` in `.env` and the environment, the key
  with `memory.me()`, that the client is a dependency with the framework's extra, and that the
  integration module imports in the project's own Python.

## 0.1.0 - unreleased

First release, moved here from the client, where it was its `init` command: `init`, `create` and
`doctor` for LangGraph, CrewAI and the OpenAI Agents SDK, writing the memory code itself into
the project.
