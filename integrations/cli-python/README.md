# alexein-cli

Memory from [Alexein](https://alexein.ai) in a LangGraph project, a CrewAI crew or an OpenAI
Agents SDK agent, as a short file you own: one command writes `memory.py` - your settings and one
configured `AlexeinMemory`, wired from the [`alexein`](https://docs.alexein.ai/sdks/python)
client's integration for your framework - and adds `alexein[<framework>]` to your project.

```bash
uvx alexein-cli init langgraph                 # a LangGraph project you have
uvx alexein-cli init crewai                    # a crew you have
uvx alexein-cli init openai-agents             # an OpenAI Agents SDK project you have
uvx alexein-cli create langgraph my-agent      # a new one, with memory wired in
uvx alexein-cli create crewai my-crew
uvx alexein-cli create openai-agents my-agent
uvx alexein-cli doctor                         # is it all set up?
uvx alexein-cli connect                        # Alexein AI in Claude Code, Cursor, VS Code, ...
uvx alexein-cli connect --remove               # ... and out of them again
uvx alexein-cli search "where does dana live"  # memory itself, once you have logged in
```

The command it installs is `alexein-cli`, also called `alexein`.

The file is yours: edit the settings, rename things, move it. What it imports - recall, saving,
the tools, failing open - comes from `alexein.langgraph`, `alexein.openai_agents` or
`alexein.crewai`, and an upgrade of `alexein` reaches it. Importing it needs no key: the client
is made on the first call to memory, from `ALEXEIN_API_KEY` and `ALEXEIN_API_URL`.

## `init`

Before it writes anything, `init` checks that it is in a Python project, that the project uses
the framework (it asks before going on in one that does not; `--yes` goes on without asking),
that what is installed is new enough (LangGraph 1.2, LangChain 1.0, the OpenAI Agents SDK 0.24,
CrewAI 1.15), and where the file goes: beside the graph `langgraph.json` names (asking when there
are several, or `--graph NAME`), beside the file that builds your `Agent`, or beside your crew.
Any of these can stop it, and then nothing has changed. An existing `memory.py` is replaced only
with `--force`.

Then it writes `memory.py`, adds `alexein[langgraph]>=0.3` (or `[openai-agents]`, `[crewai]`)
where the project does not depend on it with that extra yet - with the project's own tool: uv,
poetry, pdm, or a line in `requirements.txt` - and sets up the key: `--key tm_...`, or asked for
at a terminal. Enter skips it, and an empty `ALEXEIN_API_KEY=` waits in `.env`. `--key -` reads it
from stdin (`op read op://dev/alexein/key | uvx alexein-cli init langgraph --key - --yes`), so it is
never in your shell's history; an `ALEXEIN_API_KEY` already in the environment is used as it is. A
key it is given is checked, and a key that only reads is called out.

| Flag                         | What it does                                                 |
| ---------------------------- | ------------------------------------------------------------ |
| `--fast`                     | `FAST = True`: searches skip the relevance check, free and quicker |
| `--key`, `--base-url`        | the key and memory's address, written into `.env`            |
| `--key -`                    | the key from stdin, kept out of your shell's history         |
| `--skip-key`                 | do not ask for a key                                         |
| `--dir`, `--file`, `--graph` | where the file goes, and what it is called                   |
| `--force`                    | replace a file already there                                 |
| `--no-install`               | print the install command instead of running it              |
| `--dry-run`                  | make every check, say what would happen, change nothing      |
| `--yes`                      | ask nothing - not for the key either: give it with `--key`   |

Every file holds the same four settings, at the top:

| Setting     | Default | What it does                                                        |
| ----------- | ------- | ------------------------------------------------------------------- |
| `FAST`      | `False` | `True` answers sooner and free, a little less precisely             |
| `STRICT`    | `False` | `True` raises when memory is down, where by default a turn goes on without it |
| `MAX_CHARS` | `4000`  | how much of what memory holds goes into a prompt                    |
| `TIMEOUT`   | `10.0`  | seconds each attempt at a call may take                             |

A wrong key raises whatever `STRICT` says: that is a mistake to fix, not an outage to ride out.
Memory being down is logged on the `alexein` logger.

### LangGraph

`init langgraph` writes `memory`, with `MemoryState` and `MemoryContext`:

```python
from app.memory import MemoryContext, MemoryState, memory

builder = StateGraph(MemoryState, context_schema=MemoryContext)
builder.add_node("recall", memory.recall)  # what memory holds, into state["memory"]
builder.add_node("agent", agent)  # yours: memory.prompt(state) in its prompt
builder.add_node("remember", memory.remember)  # save the turn
builder.add_edge(START, "recall")
builder.add_edge("recall", "agent")
builder.add_edge("agent", "remember")
graph = builder.compile()

graph.invoke(
    {"messages": [HumanMessage("Where do I live?")]},
    config={"configurable": {"thread_id": "t-1"}},
    context={"user_id": "dana"},
)
```

Or give the model tools to call when it decides to:
`create_agent(model, tools=memory.tools(), context_schema=MemoryContext)` offers `memory_search`
and `memory_open`; `memory.tools(write=True)` adds `memory_add`. The nodes and tools run under
`invoke` and `ainvoke`; `memory.arecall` and `memory.aremember` are the nodes' async
counterparts.

Whose memory is read comes from the run's `context`, never from the model. A LangGraph thread is
a memory session.

### The OpenAI Agents SDK

`init openai-agents` writes `memory`, with `MemoryContext`, beside the file that builds your
`Agent` (asking when there are several, or `--dir`; with none, into the project's package):

```python
from app.memory import MemoryContext, memory

agent = Agent(name="Assistant", tools=memory.tools())
result = await Runner.run(
    agent,
    "Where do I live?",
    context=MemoryContext(user_id="dana", session_id="conv-7"),
    run_config=RunConfig(call_model_input_filter=memory.recall),
)
await memory.remember(result)  # for run_streamed, once its events are consumed
```

`memory.recall` searches once a turn and adds what it finds to the instructions of every model
call in the turn, so it is never written into a `Session`, the Conversations API or
`to_input_list()`. Any context with a `user_id` will do.

### CrewAI

`init crewai` writes `alexein_memory` - CrewAI's own memory, kept in Alexein - and `whose`,
beside a classic crew (`@CrewBase` in `src/<pkg>/crew.py`) or a JSON one (`crew.jsonc`). Flows
are not supported yet.

```python
from my_crew.memory import alexein_memory, whose


@CrewBase
class MyCrew:
    memory = alexein_memory

    @before_kickoff
    def whose_memory(self, inputs):
        return whose(inputs)

    @crew
    def crew(self) -> Crew:
        return Crew(agents=self.agents, tasks=self.tasks, memory=self.memory)


MyCrew().crew().kickoff(inputs={"user_id": "dana", "topic": "..."})
```

A JSON crew points `crew.jsonc` at the same two names:

```jsonc
"memory": {"python": "memory.alexein_memory"},
"before_kickoff_callbacks": [{"python": "memory.whose"}]
```

CrewAI then recalls the user's memory before every task, saves what each task learned, and gives
every agent its memory tools. Every kickoff names its user in `inputs["user_id"]`; the key is
checked at kickoff, once per process. `whose` is a function in the file rather than
`alexein_memory.whose` because CrewAI keeps only module-level callbacks when it restores a
checkpoint. Without CrewAI's memory: `Agent(..., tools=alexein_memory.tools("dana"))`, and
`alexein_memory.save_result("dana", output)` after the run.

## `create`

`create <framework> <name>` makes a uv project with memory wired in, and `memory.py` as `init`
writes it:

- `create langgraph` - a graph that recalls, searches and remembers, a terminal chat
  (`uv run -m <package>.chat --user dana`, where `<package>` is the name in lower case with `-`
  as `_`), and `langgraph.json` for `uv run langgraph dev`. `--model` names the model by
  `init_chat_model`'s name (default `anthropic:claude-sonnet-5-5`), whose LangChain package it
  adds.
- `create openai-agents` - an agent and a terminal chat. `--model` names the model (`MODEL` in
  `.env`); without it, the SDK's default.
- `create crewai` - a classic crew with one assistant agent and `uv run run_crew --user dana
  "..."`. `--model` takes CrewAI's `provider/model` name (default `anthropic/claude-sonnet-5-5`)
  and adds the CrewAI extra that provider needs.

It takes `init`'s `--fast` and key flags.

## `doctor`

Checks the memory file, that `alexein` is a dependency with the framework's extra, the installed
versions, that the integration module imports in the project's own `.venv`, `ALEXEIN_API_KEY`
and `ALEXEIN_API_URL` (in `.env` or the environment), the key (with `memory.me()`, which is free)
and that `.env` is not committed. Each failure says how to fix it.

`doctor --json` gives the same checks as one JSON object, for CI or an agent to read:
`{"ok": false, "root": "...", "checks": [{"ok": false, "what": "...", "fix": "..."}]}`. A check's
`ok` is `null` when it could not be made. The exit code is the same: 0 when all pass.

## `connect`

Alexein AI in the AI tools you already use, in one command - the same as `npx @alexein/cli
connect`, with no Node needed:

```bash
uvx alexein-cli connect
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
| `--json`         | with `--list`: the same as JSON, `{"tools": [{"id", "name", "found", "added"}]}`                    |
| `--remove`       | take out what `connect` added; goes with `--only`, `--dry-run` and `--yes`                          |
| `--key <key>`    | send this key in a header instead of signing in, for CI; no plugins. `--key -` reads it from stdin  |
| `--force`        | add it again where Alexein is already                                                               |
| `--dry-run`      | say what it would run or write, change nothing                                                      |
| `--yes`          | ask nothing                                                                                         |

## Memory from the shell

The memory itself, from a terminal or an AI agent's shell: search it, save to it, read one memory
whole, forget, export. `uvx alexein-cli <command>`, or `alexein <command>` once installed (`uv tool install alexein-cli`).

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

| Command                | What it does                                                                                          |
| ---------------------- | ----------------------------------------------------------------------------------------------------- |
| `search <question>`    | what memory holds for a question; `--after`, `--before`, `--provider`, `--source`, `--fast`           |
| `latest`               | the most recent memories, newest first; `--limit`                                                     |
| `open <ref>`           | one memory whole: an excerpt in full, or a fact and what it came from                                 |
| `subject <name>`       | one person or thing: its values, facts and relations                                                  |
| `summary`              | what this memory holds, in brief                                                                      |
| `history <subject>`    | every value it was said to have, and since when                                                       |
| `add <text>`, `add -`  | save something, `-` from stdin; `--id`, `--session`, `--role`, `--author`, `--self`, `--kind`, `--wait` |
| `status <item id>...`  | how far added items have got                                                                          |
| `forget`               | erase `--item`, `--session` or `--ref` for good; it asks first, or takes `--yes`                      |
| `export`               | everything, as JSON lines; `--out <file>` writes a file only you can read                             |

Every command takes `--user`, `--key`, `--base-url` and `--json`; `alexein <command> --help` lists
the rest. It exits 0 when done, 1 when memory refused or could not be reached, 2 when it was given
wrongly.

`alexein skill` prints a guide for an AI agent with a shell - when to search, when to save, what to
leave to you - to keep as its skill:
`mkdir -p ~/.claude/skills/alexein && alexein skill > ~/.claude/skills/alexein/SKILL.md`.

## License

MIT
