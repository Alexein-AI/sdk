# alexein/sdk: one surface, two languages

What every package in this repository exposes, and how it maps onto the API. The Python client
(`alexein` on PyPI) and the TypeScript client (`@alexein/sdk` on npm) are the same client: same
methods, same results, same errors. Python says `snake_case`, TypeScript `camelCase`; nothing
else differs. The integrations (`alexein.langgraph`, `@alexein/sdk/langgraph`, ...) are built on
the clients and never speak HTTP themselves. The n8n node is the one exception: n8n nodes must
not take runtime dependencies, so it calls the API directly, in the same terms.

The API's contract is `contract/openapi.json` (`/v2/openapi.json`, pinned by
`scripts/refresh-openapi.sh`). The prose reference is twin-memory-docs, `content/docs/api/*.mdx`
and `content/docs/(integrations)/sdks/*.mdx`; where this file and those pages disagree, the API's
own behaviour wins, then the docs, then this file - and this file is fixed.

## Names

| What                       | Python                                  | TypeScript / npm                        |
| -------------------------- | --------------------------------------- | --------------------------------------- |
| Client                     | `alexein` (`import alexein`)            | `@alexein/sdk`                          |
| LangGraph                  | `alexein.langgraph`, extra `[langgraph]` | `@alexein/sdk/langgraph` (peer deps)    |
| OpenAI Agents SDK          | `alexein.openai_agents`, extra `[openai-agents]` | `@alexein/sdk/openai-agents` (peer deps) |
| CrewAI                     | `alexein.crewai`, extra `[crewai]`      | -                                       |
| Scaffolding CLI            | `alexein-cli` (`uvx alexein-cli init langgraph`) | `@alexein/cli` (`npx @alexein/cli init langgraph`) |
| LiveKit                    | `alexein-livekit` (`import alexein_livekit`) | -                                   |
| n8n                        | -                                       | `@alexein/n8n-nodes-alexein`, node "Alexein", credential `alexeinApi` |
| User-Agent                 | `alexein-python/<version>[ <integration>]` | `alexein-js/<version>[ <integration>]` |
| Logger                     | `logging.getLogger("alexein")`          | `console.warn` or the `logger` option   |

Versions: every package starts at `0.3.0` (the API's `info.version`), so the docs, the clients and
the API say one number. Nothing named `twin`, `twinmemory` or "twin memory" survives in code,
docs, package metadata or user-facing strings. The product is "Alexein"; an end user of a
customer's app is an "app user".

## Settings

| Setting     | Python         | TypeScript    | Environment       | Default                  |
| ----------- | -------------- | ------------- | ----------------- | ------------------------ |
| API key     | `api_key`      | `apiKey`      | `ALEXEIN_API_KEY` | required; a clear error naming the variable and the console's API keys page |
| Base URL    | `base_url`     | `baseUrl`     | `ALEXEIN_API_URL` | `https://api.alexein.ai` |
| Timeout     | `timeout` (s)  | `timeout` (ms)|                   | 60 s per attempt         |
| Retries     | `max_retries`  | `maxRetries`  |                   | 2                        |
| Fail open   | `fail_open`    | `failOpen`    |                   | false                    |
| Integration | `integration`  | `integration` |                   | none: one lowercase token `[a-z0-9][a-z0-9._-]{0,31}` appended to the User-Agent |
| HTTP        | `http_client` (httpx) | `fetch`  |                   | a client of its own      |

The base URL is the host; the client adds `/v2`. A base URL given with a trailing `/` or a
trailing `/v2` means the same host (`http://localhost:8210/v2/` -> `http://localhost:8210`).

## Requests

- Every memory route: `POST {base}/v2/memory/<route>`, JSON body (`{}` for none). `GET {base}/v2/me`.
- Headers: `Authorization: Bearer <key>`, `User-Agent`, `Content-Type: application/json`,
  `X-Alexein-User: <user id>` on every route but `me` and `users`.
  `Idempotency-Key` on every `add` request (see Adding).
- A user id is checked client-side before any request: 1-35 characters, letters, digits, `.`,
  `_`, `-`, beginning with a letter or digit. A wrong one is a `ValueError` in Python and a
  `RangeError` in TypeScript, raised by `memory.user(id)` itself, so the mistake surfaces where it
  was made.
- Fields the caller did not set are not sent (no `null`s for absent optionals); the API's
  defaults apply.

## Retries and errors

Retried: 429 and 503, and a connection failure or timeout. Up to `max_retries` more attempts.
Wait the `Retry-After` header's seconds when present and at most 60 (more than 60: do not retry,
raise); otherwise 0.5 s * 2^attempt with ±25% jitter. Nothing else is retried. An `add` retried
sends the same `Idempotency-Key`, so a retry never saves twice.

Every error is an `AlexeinError` with `status` (null for a transport failure), `detail` (the
API's string), `errors` (on a 422: `[{field, message}]`, else empty), `request_id` /
`requestId` (the response's `X-Request-Id`) and `outage` (true for connection, timeout, 429,
and every 5xx). Subclasses:

| Class                     | When |
| ------------------------- | ---- |
| `AuthenticationError`     | 401 |
| `PermissionDeniedError`   | 403 |
| `NotFoundError`           | 404 |
| `InvalidRequestError`     | 400, 413, 422 (and any other 4xx) |
| `RateLimitError`          | 429 after retries |
| `ServiceUnavailableError` | 5xx after retries (503 and the rest) |
| `APIConnectionError`      | unreachable after retries |
| `APITimeoutError`         | subclass of `APIConnectionError`: no answer in time |

A missing key raises `AlexeinError` (Python) / `AlexeinError` (TS) at construction.

### Failing open

With `fail_open`, an error whose `outage` is true does not raise from `search` or `add` (and from
nothing else): `search` answers an empty `SearchResult` with `failed=True`; `add` saves nothing and
answers `AddResult(items=[], waiting=0, failed=True)`. Each logs one warning. Every other error
still raises.

## The client

```
memory = Memory(...)            / new Memory({...})        AsyncMemory in Python, same methods awaited
memory.me() -> Me                                          GET /v2/me
memory.user(id) -> User                                    a view: sends X-Alexein-User: id
memory.users(limit=50, cursor=None) -> UsersPage           POST /memory/users (no user header)
memory.iter_users(limit=50)  / memory.iterUsers()          every page, followed by `next`
memory.close(); context manager / `using`-free in TS
```

`User` (and `AsyncUser`):

| Method | Route | Body |
| ------ | ----- | ---- |
| `add(items, *, wait, redact, kind, session, role, author, title, about, expires, at, metadata)` | add | `{items, wait?, redact?}` |
| `search(query, *, before, after, filters, provider, source, kind, fast)` | search | as given |
| `grep(pattern, *, limit, provider, source, kind)` | grep | |
| `latest(*, k, place, after, before, filters, provider, source, kind)` | latest | |
| `around(ref, *, width)` | around | `{ref, width?}` |
| `open(ref)` | open | `{ref}` |
| `history(subject, *, attribute)` | history | |
| `summary()` | summary | `{}` |
| `facts(*, limit, cursor)` / `iter_facts(*, limit)` | facts | |
| `open_items(*, kind, provider, place, mine, within_days, limit)` | open_items | |
| `sources()` | sources | `{}` |
| `items(*, limit, cursor, filters)` / `iter_items(*, limit, filters)` | items | |
| `item(item_id)` | item | `{id}` |
| `status(ids)` | status | `{items: ids}` |
| `forget(*, items, sessions, refs)` | forget | at least one non-empty, else `ValueError` before sending |
| `correct(ref, replacement=None)` | correct | |
| `versions(item_id)` | versions | `{id}` |
| `export(*, limit, cursor)` / `iter_export(*, limit)` | export | |
| `delete()` | users/delete | `{}` - erases this app user whole |

`iter_*` are generators (async generators on `AsyncUser`; `AsyncIterable` in TS) that yield each
entry across pages, following `next` until it is null.

### Adding

`add` takes a string, an item (dict / object with `text` and the optional item fields), or a list
of either. A string is `{"text": s}`. The keyword fields fill each item that does not set its own.
Item fields: `text` (required), `kind`, `id`, `session`, `role`, `author` (string or
`{id, name, email, handle, self}`), `title`, `about` (list of `kind:name`), `at`, `expires`,
`metadata`. More than 500 items go as several requests of 500; each request carries
`Idempotency-Key: <one uuid4 for the call>-<batch index>`. The results merge into one `AddResult`.
An empty list sends nothing and answers an empty `AddResult`.

## Results

Frozen dataclasses (Python) / plain readonly objects (TS). Every result also keeps the JSON the API
sent as `raw`, so a field the API adds later is never out of reach. Absent optional fields are
`None` / `null`. TypeScript renames JSON fields to camelCase (`added_at` -> `addedAt`).

Memories (search, grep, latest, around, open), discriminated by `type`:

- `Known(text)` - a known line; `type: "known"`
- `Fact(ref, text, source, date)` - `source`: the ref of the excerpt it came from, or null; `date` only on `facts()`
- `Excerpt(ref, text, date, added_at, session, roles)`

Results:

- `SearchResult(query, answerable: bool|None, notes: list[str], memories: list[Memory], sources: list|None, failed: bool)`
  with `.known`, `.facts`, `.excerpts` (the memories of that type), `.refs` (every ref, in order),
  and `.context(max_chars=4000)` / `context(maxChars?)`: the text to paste into a prompt, exactly:
  each note on its own line, then one blank line (only when there are notes and memories), then
  each memory on its own line as `- <text>`, an excerpt with a date as `- <YYYY-MM-DD>: <text>`
  (the date's first 10 characters). Cut at a whole memory so it never exceeds `max_chars`; ""
  when there are no memories. The n8n node writes the same text.
  `SearchResult.unavailable(query)` for fail-open.
- `Memories(memories, pattern?, total?, places?)` for grep / latest / around, iterable.
- `Opened(memory: Fact|Excerpt, sources: list[Excerpt])`.
- `History(subject, values: [Value(attribute, value, since, negated)], suggestions: list|None)`.
- `Summary(items, first, last, sources, known)`.
- `FactsPage(facts, next)`, `ItemsPage(items: [StoredItem], next)`, `UsersPage(users: [AppUser(user, items, facts, last_write)], next)`, `ExportPage(user, exported_at, records, next, withheld)`.
- `OpenItems(items: [OpenItem(ref, text, date, added_at, age_days)], follow_ups: [FollowUp(title, who, date, age_days)])`.
- `StoredItem` - an item as it was added, plus `status` (`queued`|`stored`); `item(id)` answers it, or `None` when `found` is false.
- `AddResult(items: [AddedItem(id, status, redacted)], waiting, failed)`; `.ids`.
- `Statuses(items: [ItemStatus(id, status, reason)])`; `.by_id` -> `{id: status}`.
- `Forgotten(erased: Erased(items, facts, versions, waiting, relearning), complete)`.
- `Correction(retracted, text, replacement)`.
- `Versions` - whatever `/memory/versions` answers, typed as far as its documented fields go.
- `Me` - the key: `org`, `project`, `key_id`, `writes`, `label`, `created_by`, `org_name`, `project_name`, `space`, and `raw` for the rest. Read `twin-memory/src/twin_memory/api/tools.py` for its exact fields.

## Integrations

Built on the client, never on HTTP. Each takes an optional client; without one it makes one on
first use (so importing needs no key) with `fail_open=True`, `integration="<name>"` and a 10 s
timeout. Whose memory is read is decided by the developer's code, never by a model: the user id
comes from the run's context/config, never from a tool argument.

The tools a model is offered are named as the hosted MCP server names them, with the same intent:

- `memory_search(query)` - search; answers `context()` and, when any, the refs to open.
- `memory_open(ref)` - one memory whole.
- `memory_add(text)` - only when asked for write tools; saves a `note` in the run's session.

A memory outage answers the model "Memory is unavailable right now; carry on without it." unless
the integration is `strict`. A `NotFoundError` on a read of an app user with nothing saved answers
"Nothing remembered about that." / "Nothing has been remembered for this user yet."

### `alexein.langgraph` / `@alexein/sdk/langgraph`

```python
from alexein.langgraph import AlexeinMemory, MemoryState, MemoryContext

memory = AlexeinMemory()                       # or AlexeinMemory(client, fast=False, max_chars=4000, strict=False)
builder = StateGraph(MemoryState, context_schema=MemoryContext)
builder.add_node("recall", memory.recall)      # search for the latest human message -> state["memory"]
builder.add_node("agent", agent)               # put memory.prompt(state) into the system prompt
builder.add_node("remember", memory.remember)  # save the turn: last human message + last final AI reply
agent = create_agent(model, tools=memory.tools(write=True), context_schema=MemoryContext)
graph.invoke(inputs, config={"configurable": {"thread_id": "t-1"}}, context={"user_id": "dana"})
```

`recall`/`remember` work as sync and async nodes (`arecall`/`aremember`, or one callable that
LangGraph runs either way), in LangGraph's typed `(state, *, runtime)` shape. User id from
`runtime.context["user_id"]` (dict or attribute) - a tool also reads `config["configurable"]["user_id"]`
- else a `ValueError` saying how to pass it; the thread from `runtime.execution_info.thread_id`. Each saved message
keeps its LangGraph message id as the item id (else a stable hash of thread|role|text), so re-running
a turn edits rather than duplicates; the thread id is the `session`. Tool calls and tool results are
not saved. Module-level `recall`, `remember`, `memory_prompt`, `memory_tools(write=False)` use a
default `AlexeinMemory()` for the five-line case.

The TypeScript module is the same over LangGraph.js (`@langchain/langgraph`, `@langchain/core`
as optional peer dependencies): `new AlexeinMemory()`, `MemoryAnnotation` for state, `.recall`,
`.remember`, `.prompt(state)`, `.tools({ write })`.

### `alexein.openai_agents` / `@alexein/sdk/openai-agents`, `alexein.crewai`

Ported from the CLI's templates (`integrations/cli-*/templates/*/memory.*.tmpl` at the commit that
brought them in), keeping their behaviour, onto the v2 surface, as importable modules with the same
`AlexeinMemory`-style entry point and module-level defaults.

### `alexein-cli` / `@alexein/cli`

`init <framework>`, `create <framework> <dir>`, `doctor`, as today, under the new names. `init`
writes a short `memory.py` / `memory.ts` the developer owns: the settings (`FAST`, `STRICT`,
`MAX_CHARS`, `TIMEOUT`) and the wiring, importing everything else from the integration module, and
adds `alexein[<framework>]` / `@alexein/sdk` to the project's dependencies. `doctor` checks the key
with `memory.me()` and `ALEXEIN_API_KEY` / `ALEXEIN_API_URL`.

## Tests

Each package's tests run offline against a fake transport (httpx `MockTransport`; a `fetch` stub)
and check: the request each method sends (path, headers, body), the result each answer becomes,
retries, every error class, fail-open, pagination, batching and idempotency keys. A contract test
checks every route and every request field the client sends against `contract/openapi.json`. A live
test, skipped unless `ALEXEIN_API_KEY` is set, runs the quickstart against `ALEXEIN_API_URL`
(alexein-stack serves one on `http://localhost:8210`).
