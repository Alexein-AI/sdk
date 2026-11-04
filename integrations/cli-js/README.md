# twinmemory-cli for JavaScript

Memory from [Alexein](https://alexein.ai) in a LangGraph.js or OpenAI Agents SDK project, as code
you own: one command writes it, and from then on it is your file, in the manner of shadcn. The
written code uses the [`twinmemory`](https://docs.alexein.ai/sdks/typescript) client.

```bash
npx twinmemory-cli init langgraph                 # a project you have
npx twinmemory-cli init openai-agents             # ... or an OpenAI Agents SDK one
npx twinmemory-cli create langgraph my-agent      # a new one, with memory wired in
npx twinmemory-cli doctor                         # is it all set up?
```

Node 20 or newer, LangGraph.js 1.0 or newer, `@openai/agents` 0.6 or newer. For Python, see the
[docs](https://docs.alexein.ai/integrations/langgraph). The OpenAI Agents SDK has its own section,
[below](#the-openai-agents-sdk); everything up to it is LangGraph's, and what the two share - the
key, the presets, `doctor` - works the same for both.

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
| `--fast`                       | searches skip the relevance check: free and quicker     |
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

## The OpenAI Agents SDK

`init openai-agents` makes the same checks - `@openai/agents` is a dependency or imported, 0.6 or
newer - and writes `memory.ts` beside the file that builds your `Agent` (`new Agent(...)` or
`Agent.create(...)`; asking when there are several, or `--dir`; with none, into `src/` or the
root). It adds `twinmemory`, `@openai/agents` and `zod` 4 where they are missing. `--graph` is
LangGraph's and refused here.

| Name                                     | What it is                                                                                                                                                 |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `recall`                                 | a `callModelInputFilter`: searches once a turn, with the user's latest message, and adds what it finds to the instructions of every model call in the turn |
| `remember(result)`                       | saves the turn a run answered - the user's message and the final output, under the agent's name                                                            |
| `MemoryContext`                          | `{ userId, sessionId? }`; `sessionId` groups what is saved                                                                                                 |
| `MEMORY_TOOLS`, `MEMORY_WRITE_TOOLS`     | `memory_search` and `memory_read`, and `memory_add`: tools that take the user from the run's context                                                       |
| `FAST`, `STRICT`, `MAX_CHARS`, `TIMEOUT` | the settings, at the top of the file                                                                                                                       |

```ts
import { MEMORY_TOOLS, type MemoryContext, recall, remember } from "./memory.js";

const agent = new Agent({ name: "Assistant", tools: [...MEMORY_TOOLS] });
const result = await run(agent, "Where do I live?", {
  context: { userId: "dana", sessionId: "conv-7" } satisfies MemoryContext,
  callModelInputFilter: recall,
});
await remember(result); // for a stream, once `completed` resolves
```

Memory goes into the instructions, not the conversation, so it is never written into a session,
the Conversations API or `result.history`; it works the same with each. A handoff's next agent gets
it too. A wrong key throws.

`create openai-agents <name>` makes an npm project in TypeScript with `src/agent.ts`, a terminal
chat and `memory.ts`. `--model` names the model (`MODEL` in `.env`); without it, the agent uses the
SDK's default.

## License

MIT
