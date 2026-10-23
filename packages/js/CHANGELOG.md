# Changelog

## 0.1.0 - unreleased

First release: `twinmemory-cli` for LangGraph.js, the counterpart of the Python one.

- `init langgraph` writes a `memory.ts` into a LangGraph.js project - `recall` and `remember` nodes,
  `memoryPrompt`, and `MEMORY_TOOLS` / `MEMORY_WRITE_TOOLS` - as the developer's own code. It
  checks the project uses LangGraph.js 1.0 or newer and which graph the file is for before
  writing, adds what the file imports with the project's own package manager, and sets up and
  checks the key, which can be skipped. Presets: `--nodes-only`, `--tools-only`, `--fast`;
  `--dry-run`.
- `init openai-agents` does the same for an OpenAI Agents SDK project: `recall`, a
  `callModelInputFilter` that searches once a turn and puts memory in the instructions;
  `remember(result)`, which saves the turn; and the same tools. It needs `@openai/agents` 0.6 or
  newer and goes beside the file that builds the `Agent`.
- `create langgraph <name>` and `create openai-agents <name>`: a new TypeScript project with a
  graph or an agent, a terminal chat and memory wired in.
- `doctor`: whether a project is set up, each failure with its fix.
