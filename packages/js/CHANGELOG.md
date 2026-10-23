# Changelog

## 0.1.0 - unreleased

First release: `twinmemory-cli` for LangGraph.js, the counterpart of the Python one.

- `init langgraph` writes a `memory.ts` into a LangGraph.js project - `recall` and `remember` nodes,
  `memoryPrompt`, and `MEMORY_TOOLS` / `MEMORY_WRITE_TOOLS` - as the developer's own code. It
  checks the project uses LangGraph.js 1.0 or newer and which graph the file is for before
  writing, adds what the file imports with the project's own package manager, and sets up and
  checks the key, which can be skipped. Presets: `--nodes-only`, `--tools-only`, `--fast`;
  `--dry-run`.
- `create langgraph <name>`: a new TypeScript project with a graph, a terminal chat and memory
  wired in.
- `doctor`: whether a project is set up, each failure with its fix.
