# twin memory for JavaScript and TypeScript

Long-term memory for your users and agents. Add what they say; search it later in plain language.

```bash
npm install twinmemory
```

Node 20 or newer (or any runtime with `fetch`). No dependencies. ESM and CommonJS, with types.

## Quickstart

```ts
import { Memory } from "twinmemory";

const memory = new Memory(); // reads TWIN_MEMORY_API_KEY
const dana = memory.user("dana"); // your own id for one of your end users

await dana.add("I moved to Lisbon for the job at Acme.", { role: "user", session: "onboarding" });
await dana.add(
  { id: "diet", kind: "note", text: "Vegetarian, allergic to peanuts." },
  { wait: true },
);

const result = await dana.search("Where does Dana live?");
console.log(result.context()); // ready to paste into a prompt
```

Create a key in the console under **API keys**. A key belongs to one project; each end user you name
with `memory.user(...)` has a memory of their own inside it.

| Setting     | Option        | Environment variable   | Default                      |
| ----------- | ------------- | ---------------------- | ---------------------------- |
| API key     | `apiKey`      | `TWIN_MEMORY_API_KEY`  | required                     |
| Base URL    | `baseUrl`     | `TWIN_MEMORY_BASE_URL` | `https://api.twinmemory.dev` |
| Timeout     | `timeout`     |                        | 60000 ms per attempt         |
| Retries     | `maxRetries`  |                        | 2                            |
| Fail open   | `failOpen`    |                        | `false`                      |
| Integration | `integration` |                        | none                         |

For a local stack, set `TWIN_MEMORY_BASE_URL=http://localhost:8210`.

## Adding

`add` takes a string, an item, or an array of either. The options fill in what an item leaves out.

```ts
await dana.add(
  [
    { text: "Can you book the same hotel as last time?", role: "user" },
    { text: "Booked the Memmo Alfama again for 3-5 May.", role: "assistant" },
  ],
  { session: "trip-may" },
);
await dana.add("Moving house on 1 December.", { kind: "note", expires: "2026-12-31" });
```

| Item field | Meaning                                              |
| ---------- | ---------------------------------------------------- |
| `text`     | required                                             |
| `kind`     | `message` (default), `note`, or `document`           |
| `id`       | your id for it; send the same id again to replace it |
| `session`  | groups messages into one conversation                |
| `role`     | `user`, `assistant`, ...                             |
| `author`   | a name, or `{ id, name, email, handle, self }`       |
| `title`    | a document's title                                   |
| `about`    | work it names, as `kind:name` (`project:atlas`)      |
| `at`       | when it was said, ISO date or time                   |
| `expires`  | when it stops being true; it is erased then          |
| `metadata` | your own JSON                                        |

An add is accepted at once and searchable a moment later; `wait: true` returns once it is
searchable. Arrays longer than 500 items are sent in batches. Every add carries an
`Idempotency-Key`, so a retried request never saves an item twice.

## Searching

```ts
const result = await dana.search("What should I avoid cooking for Dana?");
result.known; // what is true now, as lines
result.facts; // dated facts, each with the passage it came from
result.hits; // whole passages, with their addresses
result.held; // false when memory says it does not hold the answer
result.context(4000);
```

`fast: true` skips the model filter: free and quicker, a little less precise. `before` and `after`
(ISO dates) and `scope` (a path prefix) narrow a search.

## Everything else

| Method                                              | What it does                                             |
| --------------------------------------------------- | -------------------------------------------------------- |
| `memory.me()`                                       | the key's organisation, project, and whether it writes   |
| `user.history(subject, { attribute })`              | every dated value recorded for one subject               |
| `user.latest({ k, place, after, before })`          | the most recent passages, newest first                   |
| `user.grep(pattern, { scope, limit })`              | every passage holding an exact phrase                    |
| `user.read(path)` / `user.ls(path)`                 | one file, or a directory, by a path a result gave you    |
| `user.around(passageId, { width })`                 | the passages either side of one you hold                 |
| `user.overview()`                                   | the shape of this memory and its counts                  |
| `user.forget({ items, sessions, threads, events })` | erase every copy, for good; returns a receipt            |
| `user.correct(recordId, replacement?)`              | retract one fact, optionally saying what is true instead |
| `user.versions(itemId)`                             | an item's versions, as they were sent                    |
| `user.status(ids)`                                  | how far each item has got: accepted, landed, read, ...   |
| `user.lineage(id)`                                  | what an item became, or what a fact was read from        |

Every result keeps the JSON the API sent as `.raw`.

## Errors

Every error is a `TwinMemoryError` with `status`, the API's `detail`, `requestId`, and `outage`:
whether it means memory is unavailable rather than that the request or key is wrong.

| Error                     | When                                             |
| ------------------------- | ------------------------------------------------ |
| `AuthenticationError`     | 401: no key, or one the service didn't issue     |
| `PermissionDeniedError`   | 403: the key reads, and the call writes          |
| `NotFoundError`           | 404: nothing was ever added for this end user    |
| `InvalidRequestError`     | 400, 413, 422: the request itself is wrong       |
| `RateLimitError`          | 429, after retries                               |
| `ServiceUnavailableError` | 503, after retries                               |
| `APIConnectionError`      | the service couldn't be reached, after retries   |
| `APITimeoutError`         | the service didn't answer in time, after retries |

429 and 503 are retried twice, waiting as the `Retry-After` header says. Connection errors are
retried the same way.

### Failing open

`new Memory({ failOpen: true })` rides out an outage - memory unreachable, timing out, or answering
429 or 5xx after its retries: `search` answers an empty result with `failed: true`, `add` saves
nothing and answers `failed: true`, and each logs a warning (`console.warn`, or `logger`). A wrong
key or a wrong request (401, 403, 400) still throws. Pair it with a short `timeout` where a reply
cannot wait.

`new Memory({ integration: "langgraph" })` adds a word to the `User-Agent`, so the console's
request log shows where requests came from.

## LangGraph.js

`npx twinmemory-cli init langgraph` writes memory into a LangGraph.js project as code you own,
using this client; `twinmemory-cli` lives in
[twin-memory-integrations](https://github.com/Alexein-AI/twin-memory-integrations/tree/main/packages/langgraph-js).

## Development

```bash
npm install
npm run check                 # types, formatting, tests
TWIN_MEMORY_LIVE=1 TWIN_MEMORY_API_KEY=tm_... TWIN_MEMORY_BASE_URL=http://localhost:8210 npx vitest run test/live.test.ts
npm run build                 # dist/: ESM, CommonJS and types
```

`test/openapi-memory.json` is the API's own document, pinned; `scripts/refresh-openapi.sh` refreshes
it from a running service, and `test/contract.test.ts` holds every method to it.

## License

MIT
