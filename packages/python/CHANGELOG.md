# Changelog

## 0.1.0 - unreleased

First release, moved here from the `twinmemory` client, where it was `twinmemory init`.

- `init langgraph` writes a `memory.py` into a LangGraph project - `recall` and `remember` nodes,
  `memory_prompt`, and `MEMORY_TOOLS` / `MEMORY_WRITE_TOOLS` - as the developer's own code. It
  checks the project uses LangGraph 1.0 or newer and which graph the file is for before writing,
  adds what the file imports with the project's own tool, and sets up and checks the key, which
  can be skipped. Presets: `--async`, `--nodes-only`, `--tools-only`, `--fast`; `--dry-run`.
- `create langgraph <name>`: a new uv project with a graph, a terminal chat and memory wired in.
- `doctor`: whether a project is set up, each failure with its fix.
