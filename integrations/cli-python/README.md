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
```

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
at a terminal. Enter skips it, and an empty `ALEXEIN_API_KEY=` waits in `.env`. A key it is given
is checked, and a key that only reads is called out.

| Flag                         | What it does                                                 |
| ---------------------------- | ------------------------------------------------------------ |
| `--fast`                     | `FAST = True`: searches skip the relevance check, free and quicker |
| `--key`, `--base-url`        | the key and memory's address, written into `.env`            |
| `--skip-key`                 | do not ask for a key                                         |
| `--dir`, `--file`, `--graph` | where the file goes, and what it is called                   |
| `--force`                    | replace a file already there                                 |
| `--no-install`               | print the install command instead of running it              |
| `--dry-run`                  | make every check, say what would happen, change nothing      |
| `--yes`                      | ask nothing                                                  |

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

## License

MIT
