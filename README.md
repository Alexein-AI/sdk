# twin memory for Python

Long-term memory for your users and agents. Add what they say; search it later in plain language.

```bash
pip install twinmemory
```

Python 3.10 or newer. One dependency: `httpx`.

## Quickstart

```python
from twinmemory import Memory

memory = Memory()  # reads TWIN_MEMORY_API_KEY
dana = memory.user("dana")  # your own id for one of your end users

dana.add("I moved to Lisbon for the job at Acme.", role="user", session="onboarding")
dana.add({"id": "diet", "kind": "note", "text": "Vegetarian, allergic to peanuts."}, wait=True)

result = dana.search("Where does Dana live?")
print(result.context())  # ready to paste into a prompt
```

Create a key in the console under **API keys**. A key belongs to one project; each end user you name with
`memory.user(...)` has a memory of their own inside it.

| Setting  | Argument    | Environment variable   | Default                      |
| -------- | ----------- | ---------------------- | ---------------------------- |
| API key  | `api_key`   | `TWIN_MEMORY_API_KEY`  | required                     |
| Base URL | `base_url`  | `TWIN_MEMORY_BASE_URL` | `https://api.twinmemory.dev` |
| Timeout  | `timeout`   |                        | 60 seconds                   |
| Retries  | `max_retries` |                      | 2                            |

For a local stack, set `TWIN_MEMORY_BASE_URL=http://localhost:8210`.

## Adding

`add` takes a string, an item dict, or a list of either. Keyword fields apply to every item that doesn't set
its own.

```python
dana.add(
    [
        {"text": "Can you book the same hotel as last time?", "role": "user"},
        {"text": "Booked the Memmo Alfama again for 3-5 May.", "role": "assistant"},
    ],
    session="trip-may",
)
dana.add("Moving house on 1 December.", kind="note", expires="2026-12-31")
```

| Item field | Meaning                                                                  |
| ---------- | ------------------------------------------------------------------------ |
| `text`     | required                                                                 |
| `kind`     | `message` (default), `note`, or `document`                               |
| `id`       | your id for it; send the same id again to replace it                     |
| `session`  | groups messages into one conversation                                    |
| `role`     | `user`, `assistant`, ...                                                 |
| `author`   | a name, or `{"id", "name", "email", "handle", "self"}`                   |
| `title`    | a document's title                                                       |
| `about`    | work it names, as `kind:name` (`project:atlas`)                          |
| `at`       | when it was said, ISO date or time                                       |
| `expires`  | when it stops being true; it is erased then                              |
| `metadata` | your own JSON                                                            |

An add is accepted at once and searchable a moment later. Pass `wait=True` to return once it is searchable.
Lists longer than 500 items are sent in batches. Every add carries an `Idempotency-Key`, so a retried request
never saves an item twice.

## Searching

```python
result = dana.search("What should I avoid cooking for Dana?")
result.known  # what is true now, as lines
result.facts  # dated facts, each with the passage it came from
result.hits  # whole passages, with their addresses
result.held  # False when memory says it does not hold the answer
result.context(max_chars=4000)
```

`fast=True` skips the model filter: free and quicker, a little less precise. Use it when a reply can't wait,
like a voice agent's turn. `result.filtered` says whether the filter ran.

`before` and `after` (ISO dates) and `scope` (a path prefix) narrow a search.

## Everything else

| Method                                          | What it does                                            |
| ----------------------------------------------- | ------------------------------------------------------- |
| `memory.me()`                                   | the key's organisation, project, and whether it writes  |
| `user.history(subject, attribute=None)`         | every dated value recorded for one subject              |
| `user.latest(k=10, place="", after=, before=)`  | the most recent passages, newest first                  |
| `user.grep(pattern, scope=None, limit=50)`      | every passage holding an exact phrase                   |
| `user.read(path)` / `user.ls(path)`             | one file, or a directory, by a path a result gave you   |
| `user.around(passage_id, width=2)`              | the passages either side of one you hold                |
| `user.overview()`                               | the shape of this memory and its counts                 |
| `user.forget(items=, sessions=, threads=, events=)` | erase every copy, for good; returns a receipt       |
| `user.correct(record_id, replacement=None)`     | retract one fact, optionally saying what is true instead |
| `user.versions(item_id)`                        | an item's versions, as they were sent                   |
| `user.status(ids)`                              | how far each item has got: accepted, landed, read, ...  |
| `user.lineage(id)`                              | what an item became, or what a fact was read from       |

Every result is a typed object; `.raw` holds the JSON as the API sent it.

## LangGraph

Memory goes into a LangGraph project as code you own, in the manner of shadcn: one command writes
it, and from then on it is your file.

```bash
uvx twinmemory init langgraph                 # a project you have
uvx twinmemory create langgraph my-agent      # a new one, with memory wired in
uvx twinmemory doctor                         # is it all set up?
```

### `init`

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

### `create`

`create langgraph <name>` makes a uv project with a graph, a terminal chat
(`uv run python -m <name>.chat --user dana`), `langgraph.json` for `langgraph dev`, and `memory.py`
as `init` writes it, wired in. It takes `init`'s presets and key flags, and `--model` for the model,
by `init_chat_model`'s name (default `anthropic:claude-sonnet-5-5`), whose LangChain package it
adds.

### `doctor`

Checks the memory file, the dependencies and their installed versions, the key (with one free
request) and that `.env` is not committed. Each failure says how to fix it.

## Async

```python
from twinmemory import AsyncMemory

async with AsyncMemory() as memory:
    dana = memory.user("dana")
    await dana.add("Prefers green tea.")
    result = await dana.search("What does Dana drink?", fast=True)
```

## Errors

Every error is a `TwinMemoryError` with `status`, the API's `detail`, `request_id`, and `outage`:
whether it means memory is unavailable rather than that the request or key is wrong.

| Error                       | When                                                      |
| --------------------------- | --------------------------------------------------------- |
| `AuthenticationError`       | 401: no key, or one the service didn't issue              |
| `PermissionDeniedError`     | 403: the key reads, and the call writes                   |
| `NotFoundError`             | 404: nothing was ever added for this end user             |
| `InvalidRequestError`       | 400, 413, 422: the request itself is wrong                |
| `RateLimitError`            | 429, after retries                                        |
| `ServiceUnavailableError`   | 503, after retries                                        |
| `APIConnectionError`        | the service couldn't be reached, after retries            |
| `APITimeoutError`           | the service didn't answer in time, after retries          |

429 and 503 are retried twice, waiting as the `Retry-After` header says. Connection errors are retried the
same way.

### Failing open

`Memory(fail_open=True)` rides out an outage - memory unreachable, timing out, or answering 429 or
5xx after its retries: `search` answers an empty result with `failed=True`, `add` saves nothing and
answers `failed=True`, and each logs a warning on the `twinmemory` logger. A wrong key or a wrong
request (401, 403, 400) still raises. Pair it with a short `timeout` where a reply cannot wait.

`Memory(integration="langgraph")` adds a word to the `User-Agent`, so the console's request log shows
where requests came from.

## Development

```bash
uv sync
uv run pytest                       # unit and contract tests
TWIN_MEMORY_LIVE=1 TWIN_MEMORY_API_KEY=tm_... TWIN_MEMORY_BASE_URL=http://localhost:8210 uv run pytest tests/test_live.py
```

The command line from a checkout, installing this checkout into the project instead of PyPI:

```bash
uvx --from /path/to/twin-memory-python twinmemory init langgraph --sdk /path/to/twin-memory-python
```

## License

MIT
