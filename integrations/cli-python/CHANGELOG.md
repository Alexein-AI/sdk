# Changelog

## 0.1.0 - unreleased

First release, moved here from the `twinmemory` client, where it was `twinmemory init`.

- `init langgraph` writes a `memory.py` into a LangGraph project - `recall` and `remember` nodes,
  `memory_prompt`, and `MEMORY_TOOLS` / `MEMORY_WRITE_TOOLS` - as the developer's own code. It
  checks the project uses LangGraph 1.0 or newer and which graph the file is for before writing,
  adds what the file imports with the project's own tool, and sets up and checks the key, which
  can be skipped. Presets: `--async`, `--nodes-only`, `--tools-only`, `--fast`; `--dry-run`.
- `init openai-agents` does the same for an OpenAI Agents SDK project: `recall`, a
  `call_model_input_filter` that searches once a turn and puts memory in the instructions;
  `remember(result)`, which saves the turn; and the same tools, as `function_tool`s. It needs
  `openai-agents` 0.3 or newer and goes beside the file that builds the `Agent`.
- `init crewai`: a `memory.py` for a CrewAI crew, classic or JSON. `TwinMemory` is CrewAI's own memory
  kept in Alexein - recall before every task, saves after, and the Search and Save memory tools -
  with the user held per run from `inputs["user_id"]`, and the key checked at kickoff. Needs CrewAI
  1.15 or newer. `--tools-only` writes `memory_tools` and `save_result` instead.
- `create langgraph <name>`, `create openai-agents <name>` and `create crewai <name>`: a new uv
  project with a graph, an agent or a classic crew, a terminal chat (LangGraph and the OpenAI
  Agents SDK) and memory wired in.
- `doctor`: whether a project is set up - LangGraph, the OpenAI Agents SDK or CrewAI - each failure
  with its fix.
