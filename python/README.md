# Alexein for Python

Long-term memory for your app users and agents. Add what they say; search it later in plain language.

```bash
pip install alexein
```

Python 3.10 or newer. One dependency: `httpx`. The framework integrations are extras:
`alexein[langgraph]`, `alexein[openai-agents]`, `alexein[crewai]`.

## Quickstart

```python
from alexein import Memory

memory = Memory()  # reads ALEXEIN_API_KEY
dana = memory.user("dana")  # your own id for one of your app users

dana.add("I moved to Lisbon for the job at Acme.", role="user", session="onboarding")
dana.add({"id": "diet", "kind": "note", "text": "Vegetarian, allergic to peanuts."}, wait=True)

result = dana.search("Where does Dana live?")
print(result.context())  # ready to paste into a prompt
```

Make a key in the console, under **API keys** (https://app.alexein.ai/console/keys). A key belongs to one
project; each app user you name with `memory.user(...)` has a memory of their own inside it. An app user id is
1 to 35 letters, digits, `.`, `_` or `-`, starting with a letter or digit; another raises `ValueError` where
you named it.

## Settings

| Setting     | Argument      | Environment variable | Default                      |
| ----------- | ------------- | -------------------- | ---------------------------- |
| API key     | `api_key`     | `ALEXEIN_API_KEY`    | required                     |
| Base URL    | `base_url`    | `ALEXEIN_API_URL`    | `https://api.alexein.ai`     |
| Timeout     | `timeout`     |                      | 60 seconds per attempt       |
| Retries     | `max_retries` |                      | 2                            |
| Fail open   | `fail_open`   |                      | `False`                      |
| Integration | `integration` |                      | none                         |
| HTTP client | `http_client` |                      | an `httpx.Client` of its own |

The base URL is the host: the client adds `/v2`, and `http://localhost:8210/v2/` means the same host as
`http://localhost:8210`. `integration="my-app"` adds one lowercase word to the `User-Agent`
(`alexein-python/0.3.0 my-app`), so the console's request logs show where requests came from.

## Adding

`add` takes a string, an item dict, or a list of either. Keyword fields fill every item that does not set its
own.

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

| Item field | Meaning                                                   |
| ---------- | --------------------------------------------------------- |
| `text`     | required                                                  |
| `kind`     | `message` (default), `note`, or `document`                |
| `id`       | your id for it; the same id again is an edit of that item |
| `session`  | groups messages into one conversation                     |
| `role`     | `user`, `assistant`, ...                                  |
| `author`   | a name, or `{"id", "name", "email", "handle", "self"}`    |
| `title`    | a document's title                                        |
| `about`    | work it names, as `kind:name` (`project:atlas`)           |
| `at`       | when it was said, an ISO date or time                     |
| `expires`  | when it stops being true; it is erased then               |
| `metadata` | your own JSON                                             |

An add is accepted at once and searchable a moment later; `wait=True` returns once it is searchable.
`redact=True` replaces phone numbers, cards, keys and the like before memory keeps any copy. Lists longer than
500 items go in batches, and every request carries an `Idempotency-Key` that a retry repeats, so a retried add
never saves an item twice.

## Searching

```python
result = dana.search("What should I avoid cooking for Dana?")
result.notes  # guidance for the model reading the answer
result.memories  # in order: known lines, then facts, then excerpts
result.answerable  # False when memory does not seem to hold the answer; None when not checked
result.refs  # the ref of every fact and excerpt
result.context(max_chars=4000)
```

Each memory is a `Known(text)`, a `Fact(ref, text, source)` or an `Excerpt(ref, text, date, added_at, session,
roles)`; `result.known`, `.facts` and `.excerpts` hold each kind. `dana.open(ref)` reads one whole: an
excerpt in full, or a fact with the excerpts it was learned from.

`context()` is the notes, a blank line, then each memory as `- <text>` (an excerpt after its date), cut at a
whole memory so it never exceeds `max_chars`; empty when memory found nothing.

`fast=True` answers sooner, a little less precisely, and free: use it where a reply cannot wait, like a voice
agent's turn. `before` and `after` (ISO dates), `filters`, `provider`, `source` and `kind` narrow a search.

## Everything else

| Method                                                        | What it answers                                   |
| ------------------------------------------------------------- | ------------------------------------------------- |
| `memory.me()`                                                 | the key: organisation, project, whether it writes |
| `memory.users(limit=, cursor=)` / `memory.iter_users()`       | the project's app users with memory               |
| `user.grep(pattern, limit=)`                                  | excerpts holding an exact phrase                  |
| `user.latest(k=10, place=, after=, before=)`                  | the most recent excerpts                          |
| `user.around(ref, width=2)`                                   | the excerpts either side of one                   |
| `user.open(ref)`                                              | one memory whole                                  |
| `user.history(subject, attribute=None)`                       | every value a subject was stated to have          |
| `user.summary()`                                              | counts, dates, connected apps and the known lines |
| `user.facts(limit=, cursor=)` / `user.iter_facts()`           | the facts memory learned, newest first            |
| `user.open_items(...)`                                        | open issues and pull requests, and follow-ups     |
| `user.sources()`                                              | what each connected app delivered                 |
| `user.items(limit=, cursor=, filters=)` / `user.iter_items()` | the items you added, as you added them            |
| `user.item(item_id)`                                          | one item whole, or `None`                         |
| `user.status(ids)`                                            | queued, stored, processed or unknown, per item    |
| `user.forget(items=, sessions=, refs=)`                       | erase every copy, for good; returns a receipt     |
| `user.correct(ref, replacement=None)`                         | retract one fact, optionally saying what is true  |
| `user.versions(item_id)`                                      | an item's versions, and when and why it went      |
| `user.export(limit=, cursor=)` / `user.iter_export()`         | everything memory holds for this app user         |
| `user.delete()`                                               | erase this app user whole                         |

Arguments left out are not sent, so the API's defaults apply. Every result is a frozen dataclass, and `.raw`
holds the JSON as the API sent it. The `iter_*` methods follow `next` page by page.

## Async

```python
from alexein import AsyncMemory

async with AsyncMemory() as memory:
    dana = memory.user("dana")
    await dana.add("Prefers green tea.")
    result = await dana.search("What does Dana drink?", fast=True)
    async for fact in dana.iter_facts():
        print(fact.text)
```

## Errors

Every error is an `AlexeinError` with `status` (None when no response came), `detail` (the API's sentence),
`errors` (on a 422, each field as `FieldError(field, message)`), `request_id`, and `outage`: whether memory is
unavailable rather than the request or the key being wrong.

| Error                     | When                                                                   |
| ------------------------- | ---------------------------------------------------------------------- |
| `AuthenticationError`     | 401: no key, or one the service did not issue                          |
| `PermissionDeniedError`   | 403: the key reads, and the call writes                                |
| `NotFoundError`           | 404: nothing added for this app user yet, or a ref memory did not give |
| `InvalidRequestError`     | 400, 413, 422 and any other 4xx                                        |
| `RateLimitError`          | 429, after retries                                                     |
| `ServiceUnavailableError` | 5xx, after retries                                                     |
| `APIConnectionError`      | the service could not be reached, after retries                        |
| `APITimeoutError`         | the service did not answer in time, after retries                      |

429, 503 and connection failures are retried up to `max_retries` times, waiting as `Retry-After` says (one
over 60 seconds is raised at once) or backing off from half a second. Nothing else is retried.

### Failing open

Memory being down should cost a reply its memory, not the reply. With `Memory(fail_open=True)`, an outage -
memory unreachable, timing out, or answering 429 or 5xx after its retries - does not raise from `search` or
`add`: `search` answers an empty result with `failed=True`, `add` saves nothing and answers `failed=True`, and
each logs a warning on the `alexein` logger. Every other method, and every other error (a wrong key, a wrong
request), still raises. Pair it with a short `timeout` where a reply cannot wait.

## LangGraph

```bash
pip install "alexein[langgraph]"
```

```python
from alexein.langgraph import AlexeinMemory, MemoryContext, MemoryState

memory = AlexeinMemory()  # or AlexeinMemory(client, fast=False, max_chars=4000, strict=False)

builder = StateGraph(MemoryState, context_schema=MemoryContext)
builder.add_node("recall", memory.recall)  # what memory holds for the latest message
builder.add_node("agent", agent)  # put memory.prompt(state) in its system prompt
builder.add_node("remember", memory.remember)  # save the turn
builder.add_edge(START, "recall")
builder.add_edge("recall", "agent")
builder.add_edge("agent", "remember")
graph = builder.compile(checkpointer=InMemorySaver())

graph.invoke(inputs, config={"configurable": {"thread_id": "t-1"}}, context={"user_id": "dana"})
```

Or give a model tools to call when it decides to: `create_agent(model, tools=memory.tools(write=True),
context_schema=MemoryContext)` offers `memory_search`, `memory_open` and `memory_add`.

Whose memory is read is decided by your code, never by the model: the user id comes from the run's `context`,
else from `config["configurable"]["user_id"]`, and a run without one raises a `ValueError` saying how to pass
it. Each message is saved under its LangGraph id, so a turn run again edits rather than duplicates; the thread
id is the session. Tool calls and tool results are not saved. The nodes and tools run under `invoke` and
`ainvoke`; with an `AsyncMemory`, add `memory.arecall` and `memory.aremember`. Module-level `recall`,
`remember`, `memory_prompt` and `memory_tools` use one default memory. See `examples/langgraph_agent.py`.

## OpenAI Agents SDK

```bash
pip install "alexein[openai-agents]"
```

```python
from alexein.openai_agents import AlexeinMemory, MemoryContext

memory = AlexeinMemory()
agent = Agent(name="Assistant", tools=memory.tools())
result = await Runner.run(
    agent,
    message,
    context=MemoryContext(user_id="dana", session_id="conv-7"),
    run_config=RunConfig(call_model_input_filter=memory.recall),
)
await memory.remember(result)
```

`recall` searches once a turn and adds what it finds to the instructions of every model call in that turn, so
it never lands in your session. `remember` saves the user's message and the final answer under the agent's
name. Any context with a `user_id` will do.

## CrewAI

```bash
pip install "alexein[crewai]"
```

```python
from alexein.crewai import AlexeinMemory

memory = AlexeinMemory()
crew = Crew(agents=..., tasks=..., memory=memory, before_kickoff_callbacks=[memory.whose])
crew.kickoff(inputs={"user_id": "dana", "city": "Porto"})
```

`AlexeinMemory` is CrewAI's own memory, kept in Alexein: CrewAI recalls the user's memory before every task and
saves what each task found. `whose` takes the user from the kickoff's inputs and checks the key once; a run
that names no user stops before any task. For tools with the user fixed by your code,
`Agent(..., tools=memory.tools("dana"))`, and `memory.save_result("dana", output)` after a run.

In every integration, a memory outage answers the model "Memory is unavailable right now; carry on without it."
and lets the run go on, unless `strict=True`. A wrong key raises either way. Each makes its own client on first
use, failing open with a 10 second timeout, so importing one needs no key.

## License

MIT
