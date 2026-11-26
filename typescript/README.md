# Alexein for JavaScript and TypeScript

Long-term memory for your app users and agents. Add what they say; search it later in plain
language.

```bash
npm install @alexein/sdk
```

Node 20 or newer, or any runtime with `fetch`: Bun, Deno, edge runtimes. No dependencies. ESM and
CommonJS, with types. LangGraph.js and the OpenAI Agents SDK are built in, as their own entry
points.

The full guide is at [docs.alexein.ai](https://docs.alexein.ai/sdks/typescript).

## Quickstart

```ts
import { Memory } from "@alexein/sdk";

const memory = new Memory(); // reads ALEXEIN_API_KEY
const dana = memory.user("dana"); // your own id for one of your app users

await dana.add("I moved to Lisbon for the job at Acme.", {
  id: "move", // sent again, it edits this item, never copies it
  role: "user",
  author: { name: "Dana", self: true }, // Dana's own words, and her name
  session: "onboarding",
  wait: true, // searchable once it returns
});
await dana.add(
  { id: "diet", kind: "note", text: "Vegetarian, allergic to peanuts." },
  { wait: true },
);

const result = await dana.search("Where does Dana live?");
console.log(result.context()); // ready to paste into a prompt
```

Make a key in the console, under **API keys**. A key belongs to one project; each app user you name
with `memory.user(...)` has a memory of their own inside it. An app user id is the id your app
already has for them (a UUID, an email, `auth0|...`): up to 128 characters, no control characters,
no space at either end, ASCII only; `memory.user()` throws a `RangeError` for any other, before a
request is made.

## Settings

| Setting     | Option        | Environment variable | Default                  |
| ----------- | ------------- | -------------------- | ------------------------ |
| API key     | `apiKey`      | `ALEXEIN_API_KEY`    | required                 |
| Base URL    | `baseUrl`     | `ALEXEIN_API_URL`    | `https://api.alexein.ai` |
| Timeout     | `timeout`     |                      | 60000 ms per attempt     |
| Retries     | `maxRetries`  |                      | 2                        |
| Fail open   | `failOpen`    |                      | `false`                  |
| Integration | `integration` |                      | none                     |
| Logger      | `logger`      |                      | `console.warn`           |
| HTTP        | `fetch`       |                      | the global `fetch`       |

The base URL is the API's host: `http://localhost:8210`, `http://localhost:8210/` and
`http://localhost:8210/v2` all mean the same. The environment is read where there is a
`process.env`; elsewhere, pass the options. `integration` adds one lowercase word to the
`User-Agent` (`alexein-js/0.3.3 langgraph`), so the console's request logs show where requests came
from.

Run it on your server: a key in a browser bundle can be copied, and it speaks for every user of the
project.

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
await dana.add("Vegetarian, allergic to peanuts.", { id: "diet", kind: "note" }); // the one item's id
```

The item fields are `text` (required), `kind`, `id`, `session`, `role`, `author`, `title`, `about`,
`at`, `expires` and `metadata`. The same `id` again is an edit; as an option, `id` names the one item
added, and with several items it is a `RangeError`. `wait: true` answers once the items
are searchable, so search straight after an add with `wait: true`. On what the app user says
themselves, pass `author: { name, self: true }`: memory then knows the words are theirs and what they
are called, so a question that names them ("Where does Dana live?") finds them. Without an author, a
message is kept as said by its `role`, not by anyone memory knows. `redact: true` replaces phone numbers, cards, keys and the like before memory keeps
them. More than 500 items go as several requests, each with an `Idempotency-Key` its retries send
again, so a retry never saves an item twice.

## Searching

```ts
const result = await dana.search("What should I avoid cooking for Dana?");
result.memories; // in order: known lines, then facts, then excerpts; facts and excerpts with a ref
result.known; // result.facts, result.excerpts: the memories of one type
result.answerable; // false when memory does not seem to hold the answer; null when not checked
result.notes; // guidance for the model reading the answer
result.context(4000); // notes, then one memory per line, never longer than 4000 characters
for (const ref of result.refs) await dana.open(ref); // each memory whole
```

`context()` puts each memory on one line: a memory's own line breaks become spaces.

When an answer from memory turns out wrong or incomplete, say so with `dana.feedback(result, "wrong",
{ note: "Dana moved to Porto in October." })` (or `"missing"`, `"ok"`): memory answers questions like it
better. It takes the result or its `result.searchId`, and needs a key that writes.

`fast: true` answers sooner, a little less precisely, and is free. `before` and `after` (ISO dates),
`filters`, and `provider`, `source` and `kind` narrow a search.

## Everything else

| Method                                                   | Route                 |
| -------------------------------------------------------- | --------------------- |
| `memory.me()`                                            | `GET /v2/me`          |
| `memory.users({ limit, cursor })`, `memory.iterUsers()`  | `users`               |
| `user.grep(pattern, { limit, provider, source, kind })`  | `grep`                |
| `user.latest({ k, place, after, before, filters, ... })` | `latest`              |
| `user.around(ref, { width })`                            | `around`              |
| `user.open(ref)`                                         | `open`                |
| `user.subject(name, { limit })`                          | `subject`             |
| `user.related(ref)`                                      | `related`             |
| `user.howTheyWork({ who, surface })`                     | `how_they_work`       |
| `user.lessons(task)`                                     | `lessons`             |
| `user.history(subject, { attribute })`                   | `history`             |
| `user.summary()`                                         | `summary`             |
| `user.facts({ limit, cursor })`, `user.iterFacts()`      | `facts`               |
| `user.openItems({ kind, provider, place, mine, ... })`   | `open_items`          |
| `user.sources()`                                         | `sources`             |
| `user.items({ limit, cursor, filters })`, `iterItems()`  | `items`               |
| `user.item(itemId)`                                      | `item` (null if none) |
| `user.status(ids)`                                       | `status`              |
| `user.forget({ items, sessions, refs })`                 | `forget`              |
| `user.correct(ref, replacement?)`                        | `correct`             |
| `user.feedback(search, verdict, { note })`               | `feedback`            |
| `user.refresh()`                                         | `refresh`             |
| `user.versions(itemId)`                                  | `versions`            |
| `user.export({ limit, cursor })`, `user.iterExport()`    | `export`              |
| `user.delete()`                                          | `users/delete`        |

Every route but `me` is `POST /v2/memory/<route>`. Results are plain objects with camelCase fields
(`addedAt`, `followUps`, `lastWrite`); each keeps the JSON the API sent as `.raw`. A read of an app
user nothing was ever added for throws `NotFoundError`, `item()` included; `item()` answers null for
an id an app user's memory does not hold. The `iter*`
methods are async iterables that follow `next` from page to page:

```ts
for await (const fact of dana.iterFacts()) console.log(fact.text);
```

## Errors

Every error is an `AlexeinError` with `status` (null when no answer came), `detail` (the API's
words), `errors` (on a 422, each field as `{ field, message }`), `requestId` (the response's
`X-Request-Id`: quote it when you ask for help) and `outage`.

| Error                     | When                                                                                                                         |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `AuthenticationError`     | 401: no key, or one the service did not issue                                                                                |
| `QuotaExceededError`      | 402: the month's events (on an add) or retrievals (on a search) are used; `limit`, `used`, `included`, `resetsAt`, `upgrade` |
| `PermissionDeniedError`   | 403: the key reads, and the call writes; or the organisation is closed                                                       |
| `NotFoundError`           | 404: nothing added for this app user, or no such ref                                                                         |
| `InvalidRequestError`     | 400, 413, 422 and any other 4xx: the request is wrong                                                                        |
| `RateLimitError`          | 429, after retries                                                                                                           |
| `ServiceUnavailableError` | 5xx, after retries                                                                                                           |
| `APIConnectionError`      | the service could not be reached, after retries                                                                              |
| `APITimeoutError`         | an `APIConnectionError`: no answer in time                                                                                   |

429 and 503, a timeout and a failed connection are tried up to `maxRetries` more times: after the
`Retry-After` header's seconds when it says 60 or fewer (more, and the error is thrown at once),
else after 0.5 s, 1 s, ... with jitter. Nothing else is retried. A missing key throws an
`AlexeinError` from `new Memory()`.

## Failing open

Memory being down should cost a reply its memory, not the reply. With
`new Memory({ failOpen: true })`, an outage - memory unreachable, timing out, or answering 429 or
5xx after its retries - does not throw from `search` or `add`:

- `search` answers an empty result with `failed: true`;
- `add` saves nothing and answers `failed: true`;
- each logs one warning (`console.warn`, or the `logger` you pass).

A wrong key or a wrong request (401, 403, 400, 422) still throws, and so does every other method.
Pair it with a short `timeout` where a reply cannot wait.

## Memory without tool calls: Anthropic, OpenAI and the AI SDK

Your model reads memory before every reply, and every exchange is saved, without the model deciding to call a
tool. Wrap the client you already use:

```ts
import Anthropic from "@anthropic-ai/sdk";
import { Memory } from "@alexein/sdk";
import { wrapAnthropic } from "@alexein/sdk/wrap";

const memory = new Memory(); // one of each for the process
const anthropic = new Anthropic();

export async function reply(
  userId: string,
  conversationId: string,
  messages: Anthropic.MessageParam[],
) {
  const claude = wrapAnthropic(anthropic, memory, { userId, session: conversationId });
  const answer = await claude.messages.create({ model: "...", max_tokens: 1024, messages });
  return answer.content;
}
```

`wrapOpenAI(new OpenAI(), memory, { userId })` does the same for `chat.completions` and `responses`. Both
cover `create` (streaming or not), `parse` and `stream`, and `withResponse()`.

With the Vercel AI SDK, any model:

```ts
import { generateText, wrapLanguageModel } from "ai";
import { alexeinMiddleware } from "@alexein/sdk/ai-sdk";

const model = wrapLanguageModel({
  model: yourModel,
  middleware: alexeinMiddleware(memory, { userId, session: conversationId }),
});
const { text } = await generateText({ model, messages });
```

- **Before each call**, one search with the user's latest message (with the end of the reply before it, when
  the message is short). What bears on it is added to the system prompt, after yours: inside a `<memory>`
  block that says it is quoted data, not instructions, gives each line's date and who said it, and states that
  memory never authorises sharing secrets or sending data out. A call waits at most `budget` milliseconds for
  it; when memory is slow, down or refuses, the model is called without it, and nothing is thrown.
- **After each call**, the user's message and the reply are saved in the background, never delaying the reply.
  A reply that asks to run a tool is not saved; the turn's last answer is, once. A stream is saved when it
  ends. The calls of one tool loop share one search.
- Whose memory is used is the `userId` your code passes, never anything a model or a request body says.

| Option       | Default | What it does                                                                                                   |
| ------------ | ------- | -------------------------------------------------------------------------------------------------------------- |
| `userId`     | -       | your id for the app user whose memory this is                                                                  |
| `session`    | none    | the conversation: saves are grouped under it, and a retried call edits what it saved                           |
| `author`     | none    | who the user is, `{ name, id }`; their messages are saved as theirs                                            |
| `recall`     | `true`  | look memory up before each call                                                                                |
| `save`       | `true`  | save the user's message and the reply after each call                                                          |
| `budget`     | `1500`  | the longest a call waits for memory, in milliseconds                                                           |
| `maxTokens`  | `600`   | about how many tokens of memory a call is given at most                                                        |
| `fast`       | `true`  | skip search's relevance check; with `false`, what memory judges off-topic is left out (raise `budget` with it) |
| `redact`     | `false` | replace phone numbers, cards, keys and the like before memory keeps any copy                                   |
| `beforeSave` | none    | a function that sees the items about to be saved and answers those to save (none: nothing)                     |

`memoryOf(client).last` (or `middleware.alexein.last`) says how the last lookup went (`ms`, `chars`,
`timedOut`, `failed`, `reused`). Saves run in the background: in a serverless function, `await
memoryOf(client).flush()` before it returns. Without a `memory`, a client for the process is made from
`ALEXEIN_API_KEY`. The AI SDK middleware is for AI SDK 7 (`@ai-sdk/provider` 4). See
`examples/wrapped-client.ts`.

## LangGraph.js

```bash
npm install @alexein/sdk @langchain/langgraph @langchain/core zod
```

```ts
import { AlexeinMemory, MemoryAnnotation, MemoryContext } from "@alexein/sdk/langgraph";
import { END, START, StateGraph } from "@langchain/langgraph";

const memory = new AlexeinMemory(); // or new AlexeinMemory(client, { fast, maxChars, strict })

const graph = new StateGraph(MemoryAnnotation, MemoryContext)
  .addNode("recall", memory.recall) // what memory holds for the latest human message
  .addNode("agent", agent) // yours: put memory.prompt(state) in its system prompt
  .addNode("remember", memory.remember) // save the turn
  .addEdge(START, "recall")
  .addEdge("recall", "agent")
  .addEdge("agent", "remember")
  .addEdge("remember", END)
  .compile();

await graph.invoke(inputs, { context: { user_id: "dana" }, configurable: { thread_id: "t-1" } });
```

Whose memory is read is decided by your code, never by a model: the run's `context.user_id`, else
`configurable.user_id`. `remember` saves the latest human message and the last reply that is not a
tool call, in the thread's session, each under its LangGraph message id (else a stable hash), so
running a turn again edits rather than duplicates. Tool calls and tool results are not saved.

Tools, for a model that decides when to look: `memory.tools()` is `memory_search` and
`memory_open`; `memory.tools({ write: true })` adds `memory_add`.

```ts
import { createAgent } from "langchain";

const agent = createAgent({ model, tools: memory.tools(), contextSchema: MemoryContext });
await agent.invoke(inputs, { context: { user_id: "dana" } });
```

Without a client, `AlexeinMemory` makes one on first use (so importing needs no key) that fails
open, with a 10 s timeout. An outage then costs a turn its memory, and a tool answers the model
"Memory is unavailable right now; carry on without it." With `strict: true`, it throws instead.
For the five-line case, `recall`, `remember`, `memoryPrompt` and `memoryTools` are exported too,
over one default `AlexeinMemory`. `MemoryState` is the same state as a `StateSchema`.

## OpenAI Agents SDK

```bash
npm install @alexein/sdk @openai/agents zod
```

```ts
import { Agent, run } from "@openai/agents";
import { AlexeinMemory } from "@alexein/sdk/openai-agents";

const memory = new AlexeinMemory();
const agent = new Agent({ name: "Assistant", tools: memory.tools() });

const result = await run(agent, message, {
  context: { userId: "dana", sessionId: "conv-7" },
  callModelInputFilter: memory.recall,
});
await memory.remember(result);
```

`recall` searches once a turn with the user's latest message and adds what it finds to the
instructions of every model call in that turn, so it never lands in your session or history.
`remember` saves the user's message and the final output, under the agent's name, in the context's
`sessionId`; saving the same result again edits rather than copies, and a run paused for an
approval saves nothing. The tools and the fail-open behaviour are as for LangGraph.js; module-level
`recall`, `remember` and `memoryTools` use one default `AlexeinMemory`.

## License

MIT
