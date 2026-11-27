# @alexein/cli

Memory from [Alexein](https://alexein.ai) in a LangGraph.js or OpenAI Agents SDK project, wired in
as code you own: one command writes a short `memory.ts` - your settings and one configured
`AlexeinMemory` - and adds [`@alexein/sdk`](https://docs.alexein.ai/sdks/typescript), which does
the rest.

```bash
npx @alexein/cli init langgraph                 # a LangGraph.js project you have
npx @alexein/cli init openai-agents             # ... or an OpenAI Agents SDK one
npx @alexein/cli create langgraph my-agent      # a new one, with memory wired in
npx @alexein/cli doctor                         # is it all set up?
npx @alexein/cli connect                        # Alexein AI in Claude Code, Cursor, VS Code, ...
npx @alexein/cli connect --remove               # ... and out of them again
npx @alexein/cli search "where does dana live"  # memory itself, once you have logged in
npx @alexein/cli install                        # alexein on your PATH: type alexein ... from then on
```

The command it installs is `alexein-cli`, also called `alexein`.

Node 20 or newer; LangGraph.js 1.0 or newer, or `@openai/agents` 0.21 or newer. For Python, see the
[docs](https://docs.alexein.ai/integrations/langgraph). The OpenAI Agents SDK has its own section,
[below](#the-openai-agents-sdk); everything up to it is LangGraph's, and what the two share - the
key, the presets, `doctor` - works the same for both.

## `connect`

Alexein AI in the AI tools you already use, in one command:

```bash
npx @alexein/cli connect
```

It finds Claude Code, Cursor, VS Code, GitHub Copilot CLI, Codex, Gemini CLI, Antigravity and Devin
Desktop on this computer, says which have Alexein already, and asks before adding it to the rest.
Each tool is told through its own command where it has one (`claude mcp add`, `code --add-mcp`,
`codex mcp add`, ...), so it writes its own settings. Cursor's `~/.cursor/mcp.json`, and Devin
Desktop's file when its CLI is not installed, get the `alexein` entry alone, everything else kept,
and a copy of the file beside it (`.bak`). Claude Code, Copilot CLI and Antigravity get Alexein AI's
plugin, which adds the same server and tells the agent when to search and save.

Then you sign in to Alexein from each tool, and keep **Read and save** so it can save: `connect`
says where, and starts the sign-in itself where a tool can from the terminal (Codex, Claude Code).
No key is written anywhere. claude.ai, Claude Desktop and ChatGPT are added from the app: see the
[docs](https://docs.alexein.ai/mcp).

`connect --remove` takes out what `connect` added, through each tool's own command and at the scope
it was added at (`claude plugin uninstall`, `claude mcp remove --scope user`, `copilot plugin
uninstall`, `codex mcp remove`, `gemini mcp remove --scope user`, `agy plugin uninstall`, `devin mcp
remove -s user`), and by taking the `alexein` entry out of Cursor's and VS Code's files, with a `.bak`
copy kept. It leaves a server named anything but `alexein`, and a server added to Antigravity without
its plugin, and says to take those out in the tool's own settings. Your memory is untouched, and so
is each tool's sign-in: disconnect a tool in My memory to end that too.

| Flag             | What it does                                                                                        |
| ---------------- | --------------------------------------------------------------------------------------------------- |
| `--only <tools>` | just these: `claude-code`, `cursor`, `vscode`, `copilot`, `codex`, `gemini`, `antigravity`, `devin` |
| `--no-plugin`    | the server alone, not the plugin                                                                    |
| `--list`         | which tools are here and which have Alexein; change nothing                                         |
| `--json`         | with `--list`: the same as JSON, `{ tools: [{ id, name, found, added }] }`                          |
| `--remove`       | take out what `connect` added; goes with `--only`, `--dry-run` and `--yes`                          |
| `--key <key>`    | send this key in a header instead of signing in, for CI; no plugins. `--key -` reads it from stdin  |
| `--force`        | add it again where Alexein is already                                                               |
| `--dry-run`      | say what it would run or write, change nothing                                                      |
| `--yes`          | ask nothing                                                                                         |

## Memory from the shell

The memory itself, from a terminal or an AI agent's shell: search it, save to it, read one memory
whole, forget, export. `npx @alexein/cli <command>` runs them, and so does `alexein <command>` once
the command is installed. `npx @alexein/cli install` puts it on your PATH, with
`npm install -g @alexein/cli`; `login`, `connect`, `init` and `create` offer to, once, the first time they
run at a terminal.
Upgrade it with `npm update -g @alexein/cli`.

```bash
alexein login                                  # asks for the key; or --key - and pipe it in
alexein whoami                                 # which key, from where, and whose memory
alexein search "where does dana live"
alexein add "I moved to Lisbon." --self --role user
alexein latest --json                          # the API's JSON, as it came
```

`login` checks the key, then keeps it in the system's keychain - macOS's, or the keyring through
`secret-tool` on Linux - and only what is not secret in `~/.config/alexein/credentials.json`. With
no keychain, or with `--insecure-storage`, the key goes in that file, readable only by you. A login
with either Alexein CLI, Python's or TypeScript's, serves both; `logout` takes it out.

The key is `--key`, else `ALEXEIN_API_KEY`, else your login's. Whose memory is `--user`, else
`ALEXEIN_USER`, else the app user you logged in with (`login --user`), else, for a personal key,
`me`: your own memory, the one your connected apps and AI assistants share. A project's key has no
default - its app users are the project's - so name one.

| Command               | What it does                                                                                            |
| --------------------- | ------------------------------------------------------------------------------------------------------- |
| `search <question>`   | what memory holds for a question; `--after`, `--before`, `--provider`, `--source`, `--fast`             |
| `latest`              | the most recent memories, newest first; `--limit`                                                       |
| `open <ref>`          | one memory whole: an excerpt in full, or a fact and what it came from                                   |
| `subject <name>`      | one person or thing: its values, facts and relations                                                    |
| `summary`             | what this memory holds, in brief                                                                        |
| `history <subject>`   | every value it was said to have, and since when                                                         |
| `add <text>`, `add -` | save something, `-` from stdin; `--id`, `--session`, `--role`, `--author`, `--self`, `--kind`, `--wait` |
| `status <item id>...` | how far added items have got                                                                            |
| `forget`              | erase `--item`, `--session` or `--ref` for good; it asks first, or takes `--yes`                        |
| `export`              | everything, as JSON lines; `--out <file>` writes a file only you can read                               |

Every command takes `--user`, `--key`, `--base-url` and `--json`; `alexein <command> --help` lists
the rest. It exits 0 when done, 1 when memory refused or could not be reached, 2 when it was given
wrongly.

`alexein skill` prints a guide for an AI agent with a shell - when to search, when to save, what to
leave to you - to keep as its skill:
`mkdir -p ~/.claude/skills/alexein && alexein skill > ~/.claude/skills/alexein/SKILL.md`.

## `init`

Before it writes anything, `init` checks that it is in a JavaScript project, that the project uses
LangGraph (it asks before adding LangGraph to one that does not; `--yes` adds it without asking),
that the installed `@langchain/langgraph` and `@langchain/core` are 1.0 or newer, and which graph
the file is for: `langgraph.json`'s, asking when there are several (or `--graph NAME`). Any of these
can stop it, and then nothing has changed. An existing `memory.ts` is replaced only with `--force`.

Then it writes `memory.ts` beside the graph (else into `src/`, else the root), adds `@alexein/sdk`,
`@langchain/langgraph`, `@langchain/core` and `zod` to the project's dependencies where they are
missing, with the project's own tool (npm, pnpm, yarn or bun, by its lock file or
`packageManager`), and sets up the key: `--key tm_...`, or asked for at a terminal - Enter skips it,
and an empty `ALEXEIN_API_KEY=` waits in `.env`. `--key -` reads it from stdin
(`op read op://dev/alexein/key | npx @alexein/cli init langgraph --key - --yes`), so it is never in
your shell's history; an `ALEXEIN_API_KEY` already in the environment is used as it is. A key it is
given is checked, and a key that only reads is called out when the wiring saves.

| Flag                           | What it does                                                 |
| ------------------------------ | ------------------------------------------------------------ |
| `--nodes-only`, `--tools-only` | the wiring it shows uses only the nodes, or only the tools   |
| `--fast`                       | `FAST = true`: searches skip the relevance check             |
| `--key`, `--base-url`          | `ALEXEIN_API_KEY` and `ALEXEIN_API_URL`, written into `.env` |
| `--key -`                      | the key from stdin, kept out of your shell's history         |
| `--skip-key`                   | do not ask for a key                                         |
| `--dir`, `--file`, `--graph`   | where the file goes, and what it is called                   |
| `--force`                      | replace a file already there                                 |
| `--no-install`                 | print the install command instead of running it              |
| `--dry-run`                    | make every check, say what would happen, change nothing      |
| `--yes`                        | ask nothing - not for the key either: give it with `--key`   |

What it writes, all of it yours to edit:

| Name                                     | What it is                                                           |
| ---------------------------------------- | -------------------------------------------------------------------- |
| `FAST`, `STRICT`, `MAX_CHARS`, `TIMEOUT` | the settings, at the top of the file                                 |
| `memory`                                 | an `AlexeinMemory` from `@alexein/sdk/langgraph`, made with them     |
| `MemoryAnnotation`, `MemoryState`        | the state with a `memory` field, as an Annotation or a `StateSchema` |
| `MemoryContext`                          | the context schema, with `user_id`                                   |

And what `memory` gives your graph:

| Name                            | What it is                                                                                |
| ------------------------------- | ----------------------------------------------------------------------------------------- |
| `memory.recall`                 | a node: searches the user's memory for their latest message, into `memory`                |
| `memory.remember`               | a node: saves the turn, the user's message and the final reply, under their LangGraph ids |
| `memory.prompt(state)`          | what `recall` found, as a block for your system prompt                                    |
| `memory.tools()`                | `memory_search` and `memory_open`, for a model that looks things up itself                |
| `memory.tools({ write: true })` | the same and `memory_add`, to let the model save as well                                  |

```ts
import { memory, MemoryAnnotation, MemoryContext } from "./memory.js";

const graph = new StateGraph(MemoryAnnotation, MemoryContext)
  .addNode("recall", memory.recall)
  .addNode("agent", agent) // yours: put memory.prompt(state) in its system prompt
  .addNode("remember", memory.remember)
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

`memory` makes its client on first use, from the settings, so importing `memory.ts` needs no key;
`ALEXEIN_API_KEY` must be set by the first run: `langgraph dev` reads `.env` when `langgraph.json`
has `"env": ".env"`, and a script imports `dotenv/config`. `ALEXEIN_API_URL` is the API's address,
`https://api.alexein.ai` unless set.

Memory being down does not take the graph down: with `STRICT = false`, the default, a turn goes
ahead without its memory, a save is skipped, a tool tells the model memory is unavailable, and each
is logged. A wrong key still throws - that is a mistake to fix.

## `create`

`create langgraph <name>` makes an npm project in TypeScript with a graph, a terminal chat
(`npm run chat -- --user dana`), `langgraph.json` for `npm run dev`, and `memory.ts` as `init`
writes it, wired in. It takes `init`'s presets and key flags, and `--model` for the model, by
`initChatModel`'s name (default `anthropic:claude-sonnet-5-5`), whose LangChain package it adds.

## `doctor`

Checks the memory file, that `@alexein/sdk` and the framework's packages are dependencies and
installed new enough, where `ALEXEIN_API_KEY` and `ALEXEIN_API_URL` come from (`.env`, else the
environment), the key itself with `memory.me()` (one free request), and that `.env` is not
committed. Each failure says how to fix it.

`doctor --json` gives the same checks as one JSON object, for CI or an agent to read:
`{ "ok": false, "root": "...", "checks": [{ "ok": false, "what": "...", "fix": "..." }] }`. A
check's `ok` is `null` when it could not be made. The exit code is the same: 0 when all pass.

## The OpenAI Agents SDK

`init openai-agents` makes the same checks - `@openai/agents` is a dependency or imported, 0.21 or
newer - and writes `memory.ts` beside the file that builds your `Agent` (`new Agent(...)` or
`Agent.create(...)`; asking when there are several, or `--dir`; with none, into `src/` or the
root). It adds `@alexein/sdk`, `@openai/agents` and `zod` 4 where they are missing. `--graph` is
LangGraph's and refused here.

The file holds the same settings and a `memory`, an `AlexeinMemory` from
`@alexein/sdk/openai-agents`, and re-exports the `MemoryContext` type, `{ userId, sessionId? }`:

| Name                                              | What it is                                                                                                                                                 |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `memory.recall`                                   | a `callModelInputFilter`: searches once a turn, with the user's latest message, and adds what it finds to the instructions of every model call in the turn |
| `memory.remember(result)`                         | saves the turn a run answered - the user's message and the final output, under the agent's name                                                            |
| `memory.tools()`, `memory.tools({ write: true })` | `memory_search` and `memory_open`, and `memory_add`: tools that take the user from the run's context                                                       |

```ts
import { memory, type MemoryContext } from "./memory.js";

const agent = new Agent({ name: "Assistant", tools: memory.tools() });
const result = await run(agent, "Where do I live?", {
  context: { userId: "dana", sessionId: "conv-7" } satisfies MemoryContext,
  callModelInputFilter: memory.recall,
});
await memory.remember(result); // for a stream, once `completed` resolves
```

Memory goes into the instructions, not the conversation, so it is never written into a session,
the Conversations API or `result.history`; it works the same with each. A handoff's next agent gets
it too. A wrong key throws.

`create openai-agents <name>` makes an npm project in TypeScript with `src/agent.ts`, a terminal
chat and `memory.ts`. `--model` names the model (`MODEL` in `.env`); without it, the agent uses the
SDK's default.

## License

MIT
