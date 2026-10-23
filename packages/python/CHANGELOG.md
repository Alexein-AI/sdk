# Changelog

## 0.1.0 - unreleased

First release, moved here from the `twinmemory` client, where it was `twinmemory init`.

- `init langgraph` writes a `memory.py` into a LangGraph project - `recall` and `remember` nodes,
  `memory_prompt`, and `MEMORY_TOOLS` / `MEMORY_WRITE_TOOLS` - as the developer's own code. It
  checks the project uses LangGraph 1.0 or newer and which graph the file is for before writing,
  adds what the file imports with the project's own tool, and sets up and checks the key, which
  can be skipped. Presets: `--async`, `--nodes-only`, `--tools-only`, `--fast`; `--dry-run`.
- `create langgraph <name>`: a new uv project with a graph, a terminal chat and memory wired in.
- `init crewai`: a `memory.py` for a CrewAI crew, classic or JSON. `TwinMemory` is CrewAI's own memory
  kept in twin memory - recall before every task, saves after, and the Search and Save memory tools -
  with the user held per run from `inputs["user_id"]`, and the key checked at kickoff. Needs CrewAI
  1.15 or newer. `--tools-only` writes `memory_tools` and `save_result` instead.
- `create crewai <name>`: a new classic crew with memory wired in.
- `doctor`: whether a project is set up - LangGraph or CrewAI - each failure with its fix.
