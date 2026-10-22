# twinmemory-cli for LangGraph.js

Memory from [twin memory](https://twinmemory.dev) in a LangGraph.js project, as code you own: one
command writes it, and from then on it is your file, in the manner of shadcn. The written code uses
the [`twinmemory`](https://github.com/Alexein-AI/twin-memory-js) client.

```bash
npx twinmemory-cli init langgraph                 # a project you have
npx twinmemory-cli create langgraph my-agent      # a new one, with memory wired in
npx twinmemory-cli doctor                         # is it all set up?
```

Node 20 or newer, LangGraph.js 1.0 or newer. For Python, see
[`../langgraph-python`](../langgraph-python).

## `init`

Before it writes anything, `init` checks that it is in a JavaScript project, that the project uses
LangGraph (it asks before adding LangGraph to one that does not; `--yes` adds it without asking),
that the installed `@langchain/langgraph` and `@langchain/core` are 1.0 or newer, and which graph
the file is for: `langgraph.json`'s, asking when there are several (or `--graph NAME`). Any of these
can stop it, and then nothing has changed. An existing `memory.ts` is replaced only with `--force`.

Then it writes `memory.ts` beside the graph (else into `src/`, else the root), adds `twinmemory`,
`@langchain/langgraph`, `@langchain/core` and `zod` where they are missing, with the project's own
tool (npm, pnpm, yarn or bun, by its lock file or `packageManager`), and sets up the key:
`--key tm_...`, or asked for at a terminal - Enter skips it, and an empty `TWIN_MEMORY_API_KEY=`
waits in `.env`. A key it is given is checked, and a key that only reads is called out when the file
saves.

| Flag                           | What it does                                            |
| ------------------------------ | ------------------------------------------------------- |
| `--nodes-only`, `--tools-only` | the file holds only the nodes, or only the tools        |
| `--fast`                       | searches skip the model filter: free and quicker        |
| `--key`, `--base-url`          | the key and memory's address, written into `.env`       |
| `--skip-key`                   | do not ask for a key                                    |
| `--dir`, `--file`, `--graph`   | where the file goes, and what it is called              |
| `--force`                      | replace a file already there                            |
| `--no-install`                 | print the install command instead of running it         |
| `--dry-run`                    | make every check, say what would happen, change nothing |
| `--yes`                        | ask nothing                                             |

What it writes, all of it yours to edit:

| Name                                     | What it is                                                                                |
| ---------------------------------------- | ----------------------------------------------------------------------------------------- |
| `recall`                                 | a node: searches the user's memory for their latest message, into `memory`                |
| `remember`                               | a node: saves the turn, the user's message and the final reply, under their LangGraph ids |
| `memoryPrompt(state)`                    | what `recall` found, as a block for your system prompt                                    |
| `MemoryState`, `MemoryContext`           | the state with a `memory` field, and the context schema with `user_id`                    |
| `MEMORY_TOOLS`                           | `memory_search` and `memory_read`, for a model that looks things up itself                |
| `MEMORY_WRITE_TOOLS`                     | the same and `memory_add`, to let the model save as well                                  |
| `useMemory(client)`                      | use a client of your own: another key, or a stand-in in tests                             |
| `FAST`, `STRICT`, `MAX_CHARS`, `TIMEOUT` | the settings, at the top of the file                                                      |

```ts
import { MemoryContext, MemoryState, memoryPrompt, recall, remember } from "./memory.js";

const graph = new StateGraph(MemoryState, MemoryContext)
  .addNode("recall", recall)
  .addNode("agent", agent) // yours: put memoryPrompt(state) in its system prompt
  .addNode("remember", remember)
  .addEdge(START, "recall")
  .addEdge("recall", "agent")
  .addEdge("agent", "remember")
  .compile();

await graph.invoke(
  { messages: [new HumanMessage("Where do I live?")] },
  { context: { user_id: "dana" }, configurable: { thread_id: "t-1" } },
);
```

Whose memory is read comes from the run's `context` (or `configurable.user_id`), never from the
model: a tool's run config is filled in by LangGraph, and the model does not see it. A LangGraph
thread is a memory session.

Memory being down does not take the graph down: with `STRICT = false`, the default, a turn goes
ahead without its memory, a save is skipped, a tool tells the model memory is unavailable, and each
is logged. A wrong key still throws - that is a mistake to fix.

## `create`

`create langgraph <name>` makes an npm project in TypeScript with a graph, a terminal chat
(`npm run chat -- --user dana`), `langgraph.json` for `npm run dev`, and `memory.ts` as `init`
writes it, wired in. It takes `init`'s presets and key flags, and `--model` for the model, by
`initChatModel`'s name (default `anthropic:claude-sonnet-5-5`), whose LangChain package it adds.

## `doctor`

Checks the memory file, the dependencies and their installed versions, the key (with one free
request) and that `.env` is not committed. Each failure says how to fix it.

## Development

```bash
npm install          # twinmemory comes from ../../../twin-memory-js until it is on npm
npm run check        # types, formatting, and the tests: the CLI, and every file it writes run
                     # inside real LangGraph.js graphs, type-checked and formatted as written
npm run build        # dist/bin.js
node dist/bin.js init langgraph --sdk /path/to/twin-memory-js
```

## License

MIT
