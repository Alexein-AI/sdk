# twinmemory-cli

Memory from [twin memory](https://twinmemory.dev) in a LangGraph or OpenAI Agents SDK project, as
code you own: one command writes it, and from then on it is your file, in the manner of shadcn. The
written code uses the [`twinmemory`](https://github.com/Alexein-AI/twin-memory-python) client.

```bash
uvx twinmemory-cli init langgraph                 # a project you have
uvx twinmemory-cli init openai-agents             # ... or an OpenAI Agents SDK one
uvx twinmemory-cli create langgraph my-agent      # a new one, with memory wired in
uvx twinmemory-cli doctor                         # is it all set up?
```

The OpenAI Agents SDK has its own section, [below](#the-openai-agents-sdk); everything up to it is
LangGraph's, and what the two share - the key, the presets, `doctor` - works the same for both.

## `init`

Before it writes anything, `init` checks that it is in a Python project, that the project uses
LangGraph (it asks before adding LangGraph to one that does not; `--yes` adds it without asking),
that the installed `langgraph` and `langchain` are 1.0 or newer, and which graph the file is for:
`langgraph.json`'s, asking when there are several (or `--graph NAME`). Any of these can stop it, and
then nothing has changed. An existing `memory.py` is replaced only with `--force`.

Then it writes `memory.py` beside the graph (else into `src/<package>/`, `app/` or the root), adds
`twinmemory>=0.2`, `langgraph>=1.0` and `langchain>=1.0` where they are missing, with the project's
own tool (uv, poetry, pdm, or lines in `requirements.txt`), and sets up the key: `--key tm_...`, or
asked for at a terminal - Enter skips it, and an empty `TWIN_MEMORY_API_KEY=` waits in `.env`. A
key it is given is checked, and a key that only reads is called out when the file saves.

| Flag                         | What it does                                                    |
| ---------------------------- | --------------------------------------------------------------- |
| `--nodes-only`, `--tools-only` | the file holds only the nodes, or only the tools              |
| `--async`                    | async nodes and tools, for `ainvoke`, `langgraph dev` and Platform |
| `--fast`                     | searches skip the model filter: free and quicker                |
| `--key`, `--base-url`        | the key and memory's address, written into `.env`               |
| `--skip-key`                 | do not ask for a key                                            |
| `--dir`, `--file`, `--graph` | where the file goes, and what it is called                      |
| `--force`                    | replace a file already there                                    |
| `--no-install`               | print the install command instead of running it                 |
| `--dry-run`                  | make every check, say what would happen, change nothing         |
| `--yes`                      | ask nothing                                                     |

What it writes, all of it yours to edit:

| Name                              | What it is                                                     |
| --------------------------------- | -------------------------------------------------------------- |
| `recall`                          | a node: searches the user's memory for their latest message, into `state["memory"]` |
| `remember`                        | a node: saves the turn, the user's message and the final reply, under their LangGraph ids |
| `memory_prompt(state)`            | what `recall` found, as a block for your system prompt         |
| `MemoryState`, `MemoryContext`    | the state with a `memory` key, and the context schema with `user_id` |
| `MEMORY_TOOLS`                    | `memory_search` and `memory_read`, for a model that looks things up itself |
| `MEMORY_WRITE_TOOLS`              | the same and `memory_add`, to let the model save as well       |
| `FAST`, `STRICT`, `MAX_CHARS`, `TIMEOUT` | the settings, at the top of the file                    |

```python
from app.memory import MemoryContext, MemoryState, memory_prompt, recall, remember

builder = StateGraph(MemoryState, context_schema=MemoryContext)
builder.add_node("recall", recall)
builder.add_node("agent", agent)  # yours: put memory_prompt(state) in its system prompt
builder.add_node("remember", remember)
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

Whose memory is read comes from the run's `context` (or `config["configurable"]["user_id"]`), never
from the model: the tools take the user from LangGraph's runtime, which the model does not see. A
LangGraph thread is a memory session.

Memory being down does not take the graph down: with `STRICT = False`, the default, a turn goes
ahead without its memory, a save is skipped, a tool tells the model memory is unavailable, and each
is logged on the `twinmemory` logger. A wrong key still raises - that is a mistake to fix.

## `create`

`create langgraph <name>` makes a uv project with a graph, a terminal chat
(`uv run python -m <name>.chat --user dana`), `langgraph.json` for `langgraph dev`, and `memory.py`
as `init` writes it, wired in. It takes `init`'s presets and key flags, and `--model` for the model,
by `init_chat_model`'s name (default `anthropic:claude-sonnet-5-5`), whose LangChain package it
adds.

## `doctor`

Checks the memory file, the dependencies and their installed versions, the key (with one free
request) and that `.env` is not committed. Each failure says how to fix it.

## The OpenAI Agents SDK

`init openai-agents` makes the same checks - the SDK is a dependency or imported, `openai-agents`
0.3 or newer - and writes `memory.py` beside the file that builds your `Agent` (asking when there
are several, or `--dir`; with none, into the project's package). The file is async: the SDK is.
`--graph` and `--async` are LangGraph's and refused here.

| Name                              | What it is                                                     |
| --------------------------------- | -------------------------------------------------------------- |
| `recall`                          | a `call_model_input_filter`: searches once a turn, with the user's latest message, and adds what it finds to the instructions of every model call in the turn |
| `remember(result)`                | saves the turn a run answered - the user's message and the final output, under the agent's name |
| `MemoryContext`                   | `user_id`, and an optional `session_id` that groups what is saved |
| `MEMORY_TOOLS`, `MEMORY_WRITE_TOOLS` | as above: `function_tool`s that take the user from the run's context |
| `FAST`, `STRICT`, `MAX_CHARS`, `TIMEOUT` | the settings, at the top of the file                    |

```python
from app.memory import MEMORY_TOOLS, MemoryContext, recall, remember

agent = Agent(name="Assistant", tools=[*MEMORY_TOOLS])
result = await Runner.run(
    agent,
    "Where do I live?",
    context=MemoryContext(user_id="dana", session_id="conv-7"),
    run_config=RunConfig(call_model_input_filter=recall),
)
await remember(result)  # for run_streamed, once its events are consumed
```

Memory goes into the instructions, not the conversation, so it is never written into a `Session`,
the Conversations API or `to_input_list()`; it works the same with each. A handoff's next agent
gets it too. Any context with a `user_id` will do, an object or a dict. A wrong key raises: from
a tool, as the SDK's `UserError` with memory's error as its cause.

`create openai-agents <name>` makes a uv project with `agent.py`, a terminal chat and `memory.py`.
`--model` names the model (`MODEL` in `.env`); without it, the agent uses the SDK's default.

## Development

```bash
uv sync                  # twinmemory comes from ../../vendor until it is on PyPI
uv run pytest            # the CLI, and every file it writes run inside real LangGraph graphs,
                         # and the OpenAI Agents SDK's Runner with its scripted model
uv run ruff check . && uv run pyright
```

From a checkout, installing a checkout of the client into the project instead of PyPI:

```bash
uvx --from . twinmemory-cli init langgraph --sdk /path/to/twin-memory-python
```

## License

MIT
