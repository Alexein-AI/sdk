# Changelog

## 0.3.0 - unreleased

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
