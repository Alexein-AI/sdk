# Alexein for Python

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

| Setting  | Argument      | Environment variable   | Default                  |
| -------- | ------------- | ---------------------- | ------------------------ |
| API key  | `api_key`     | `TWIN_MEMORY_API_KEY`  | required                 |
| Base URL | `base_url`    | `TWIN_MEMORY_BASE_URL` | `https://api.alexein.ai` |
| Timeout  | `timeout`     |                        | 60 seconds               |
| Retries  | `max_retries` |                        | 2                        |

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
| `id`       | your id for it; the same id again is an edit of that item                |
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
result.known  # short lines: every value as stated, dated, newest first
result.facts  # dated facts, each with the passage it came from
result.hits  # whole passages, with their addresses
result.held  # False when memory's own check finds it does not hold the answer
result.context(max_chars=4000)
```

`fast=True` skips the relevance check: free and quicker, a little less precise. Use it when a reply can't
wait, like a voice agent's turn. `result.filtered` says whether search's relevance check ran, and
`result.held` is None when it did not.

`before` and `after` (ISO dates) and `scope` (a path prefix) narrow a search.

## Everything else

| Method                                          | What it does                                            |
| ----------------------------------------------- | ------------------------------------------------------- |
| `memory.me()`                                   | the key's organisation, project, and whether it writes  |
| `user.history(subject, attribute=None)`         | every dated value recorded for one subject              |
| `user.latest(k=10, place="", after=, before=)`  | the most recent passages, newest first                  |
| `user.grep(pattern, scope=None, limit=50)`      | every passage holding an exact phrase                   |
| `user.read(path)` / `user.ls(path)`             | one passage whole, or what is under a path              |
| `user.around(passage_id, width=2)`              | the passages either side of one you hold                |
| `user.overview()`                               | what this memory holds: directories, counts and a short written guide |
| `user.forget(items=, sessions=, threads=, events=)` | erase every copy, for good; returns a receipt       |
| `user.correct(record_id, replacement=None)`     | retract one fact, optionally saying what is true instead |
| `user.versions(item_id)`                        | an item's versions, as they were sent                   |
| `user.status(ids)`                              | how far each item has got: accepted, landed, read, ...  |
| `user.lineage(id)`                              | what an item became, or what a fact came from           |

Every result is a typed object; `.raw` holds the JSON as the API sent it.

## LangGraph

`twinmemory-cli` (coming soon) will write memory into a LangGraph project as code you own, using this
client. Until then, see [LangGraph](https://docs.alexein.ai/integrations/langgraph).

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

## License

MIT
