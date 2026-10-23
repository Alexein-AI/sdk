# twinmemory-cli

Memory from [twin memory](https://twinmemory.dev) in a LangGraph project or a CrewAI crew, as code
you own: one command writes it, and from then on it is your file, in the manner of shadcn. The written
code uses the [`twinmemory`](https://github.com/Alexein-AI/twin-memory-python) client.

```bash
uvx twinmemory-cli init langgraph                 # a project you have
uvx twinmemory-cli init crewai                    # a crew you have
uvx twinmemory-cli create langgraph my-agent      # a new one, with memory wired in
uvx twinmemory-cli create crewai my-crew
uvx twinmemory-cli doctor                         # is it all set up?
```

The LangGraph sections come first; [CrewAI](#crewai) has its own.

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

## CrewAI

`init crewai` writes `memory.py` beside a crew - classic (`@CrewBase` in `src/<pkg>/crew.py`) or JSON
(`crew.jsonc`, what `crewai create` makes by default) - and installs `twinmemory`. It needs CrewAI 1.15
or newer; a newer minor than the one this release was tested with works, with a warning. Flows are
not supported yet.

By default the file holds `TwinMemory`, CrewAI's own memory kept in twin memory. Give it to the crew
and CrewAI recalls the user's memory before every task, saves what each task found, and gives every
agent its "Search memory" and "Save to memory" tools:

```python
from my_crew.memory import TwinMemory, whose

@CrewBase
class MyCrew:
    memory = TwinMemory()

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
"memory": {"python": "memory.twin_memory"},
"before_kickoff_callbacks": [{"python": "memory.whose"}]
```

- **Whose memory** is the run's `inputs["user_id"]`, required on every kickoff; the model never
  chooses it. It is held per run, so one `TwinMemory` serves concurrent runs for different users.
- **The key is checked at kickoff**, once per process, because CrewAI swallows memory's errors: a wrong
  key stops the run there instead of quietly turning memory off.
- **Memory being down** costs a task its memory, not the run; every failure is logged on the
  `twinmemory` logger.
- `--tools-only` writes `memory_tools(user_id)` and `save_result(user_id, output)` instead, for a crew
  that does not use CrewAI's memory.

`create crewai <name>` makes a classic crew with memory wired in: one assistant agent, its task, and
`uv run run_crew --user dana "..."`. `--model` takes CrewAI's `provider/model` name (default
`anthropic/claude-sonnet-5-5`) and adds the CrewAI extra that provider needs.

## Development

```bash
uv sync                  # twinmemory comes from ../../vendor until it is on PyPI
uv run pytest            # the CLI, and every file it writes run inside real LangGraph graphs
uv run ruff check . && uv run pyright
```

From a checkout, installing a checkout of the client into the project instead of PyPI:

```bash
uvx --from . twinmemory-cli init langgraph --sdk /path/to/twin-memory-python
```

## License

MIT
