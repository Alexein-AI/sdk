# How the Alexein n8n node works

This explains `@alexein/n8n-nodes-alexein` from end to end: what n8n loads, what each file does, what goes over
the wire, how an AI Agent uses the node, and every setting involved. For testing and publishing, see
[TESTING-AND-PUBLISHING.md](TESTING-AND-PUBLISHING.md).

Version 0.3.0, against the Alexein API's `/v2` surface (`contract/openapi.json` at the root of this repository),
tested with n8n 2.44.6. What users read is the README and https://docs.alexein.ai/integrations/n8n; this note is
for whoever works on the node, and does not ship.

## Contents

1. [The whole picture](#1-the-whole-picture)
2. [The files](#2-the-files)
3. [How n8n finds the node](#3-how-n8n-finds-the-node)
4. [The credential](#4-the-credential)
5. [The node's fields](#5-the-nodes-fields)
6. [What happens when the node runs](#6-what-happens-when-the-node-runs)
7. [Each operation, as sent and as returned](#7-each-operation-as-sent-and-as-returned)
8. [The search context](#8-the-search-context)
9. [Errors](#9-errors)
10. [As an AI Agent tool](#10-as-an-ai-agent-tool)
11. [App users, and whose memory a call reaches](#11-app-users-and-whose-memory-a-call-reaches)
12. [The Telegram template](#12-the-telegram-template)
13. [MCP instead of the node](#13-mcp-instead-of-the-node)
14. [Every variable and setting](#14-every-variable-and-setting)
15. [Limits](#15-limits)
16. [Why it is built this way](#16-why-it-is-built-this-way)
17. [Tests](#17-tests)

---

## 1. The whole picture

```text
 n8n workflow                                             Alexein API
 ─────────────────────────────────────────────            ──────────────────────────
 [Trigger] ──► [Alexein: Add] ──► [Alexein: Search] ──► ...
                     │                     │
                     │  POST /v2/memory/add │  POST /v2/memory/search
                     │  Authorization: Bearer tm_...   (from the credential)
                     │  X-Alexein-User: user_42        (from the App User field)
                     ▼                     ▼
               ┌──────────────────────────────────────────┐
               │ key → organisation + project              │
               │ + App User → one memory of its own        │
               └──────────────────────────────────────────┘
```

The node is a thin client. It turns n8n parameters into HTTP requests to the Alexein API, and turns the answers
back into n8n items. It holds no memory itself and no state between runs.

It speaks the same surface as the SDKs (`docs/DESIGN.md` at the root of this repository): the same routes, the
same words (memories, facts, excerpts, refs, app users). It calls HTTP itself rather than using `@alexein/sdk`,
because n8n won't verify a community node with runtime dependencies.

It is used in two ways:

- **As a normal node** in a workflow: one request per input item (Add groups them; see section 6).
- **As an AI Agent tool:** n8n makes a copy of it, "Alexein Tool", which an agent can call. The model fills in
  some fields, such as the search question (section 10).

## 2. The files

```text
integrations/n8n/
├── package.json                       the npm package; its "n8n" field tells n8n what to load
├── credentials/
│   └── AlexeinApi.credentials.ts      the "Alexein API" credential: key, base URL, test
├── nodes/Alexein/
│   ├── Alexein.node.ts                the node: its description, and execute() that sends requests
│   ├── fields.ts                      every field the user sees: resource, operation, app user, ...
│   ├── requests.ts                    pure functions: parameters → request; pages; the search context
│   └── Alexein.node.json              "codex": categories and documentation links for n8n's panel
├── icons/                             alexein.svg (light) and alexein.dark.svg (dark)
├── templates/telegram-assistant-memory.json   the Telegram assistant workflow
├── test/                              unit tests, run with Node's own test runner against dist/
├── e2e/                               real n8n in Docker against an Alexein API
├── eslint.config.mjs, tsconfig.json, .prettierrc.js   n8n's standard tooling, from its scaffold
├── CONTRIBUTING.md, HOW-IT-WORKS.md, TESTING-AND-PUBLISHING.md   notes for whoever works on the node (not shipped)
└── AGENTS.md, CLAUDE.md, .agents/     n8n's scaffold guidance for whoever edits the node next (not shipped)
```

Only `dist/` (the compiled JavaScript, the icons and the codex file), `package.json`, `README.md` and `LICENSE`
are published to npm. That's the `files` entry in `package.json`: `dist`, less its source maps and the copy of
`package.json` that `tsc` puts there; npm adds the README, licence and package.json itself.

## 3. How n8n finds the node

`package.json` carries a block n8n reads when the package is installed:

```json
"keywords": ["n8n-community-node-package", ...],
"n8n": {
  "n8nNodesApiVersion": 1,
  "strict": true,
  "credentials": ["dist/credentials/AlexeinApi.credentials.js"],
  "nodes": ["dist/nodes/Alexein/Alexein.node.js"]
}
```

- **The keyword** is how npm search and n8n recognise a community node package.
- **`n8nNodesApiVersion: 1`** is the node API version this package is written against.
- **`strict: true`** opts in to n8n's stricter checks. They're required for verification.
- **`credentials` and `nodes`** are the compiled files n8n loads.
- **`publishConfig.access: public`**: a scoped package is private on npm unless it says otherwise.

**Where it lives in n8n:**

- **Installed from the UI** (Settings > Community Nodes): the package goes to `~/.n8n/nodes/node_modules/` and
  the node type is `@alexein/n8n-nodes-alexein.alexein`.
- **Linked during development** (`npm run dev`, or the e2e test): it goes to `~/.n8n/custom/node_modules/` and
  n8n names it `CUSTOM.alexein`.

For every node with `usableAsTool: true`, n8n also creates a second type with `Tool` added to the name,
`@alexein/n8n-nodes-alexein.alexeinTool`. That is the "Alexein Tool" an AI Agent sees.

## 4. The credential

File: `credentials/AlexeinApi.credentials.ts`. n8n shows it as **Alexein API**; its internal name is
`alexeinApi`.

| Field    | Internal name | Required | Default                  | Stored encrypted                    |
| -------- | ------------- | -------- | ------------------------ | ----------------------------------- |
| API Key  | `apiKey`      | yes      | (empty)                  | yes (password field)                |
| Base URL | `baseUrl`     | yes      | `https://api.alexein.ai` | yes (n8n encrypts every credential) |

**The Base URL is the host.** The node adds `/v2` itself, and drops a trailing `/` or `/v2` from what is set,
so `http://localhost:8210/v2/` and `http://localhost:8210` are the same (`host()` in `requests.ts`; the Test's
expression does the same).

**How it signs requests.** The `authenticate` block tells n8n to add one header to every request the node
makes through `httpRequestWithAuthentication`:

```text
Authorization: Bearer <apiKey>
```

**How the Test button works.** The `test` block makes n8n send:

```text
GET <Base URL as the host>/v2/me
Authorization: Bearer <apiKey>
```

A `200` shows "Connection successful". The API answers `/v2/me` with what the key is, for example
`{"kind": "key", "org": "o7k2…", "project": "production", "key_id": "key_…", "writes": true}`. A `401` (a key
the API didn't issue) shows as a failed test. `/v2/me` names no app user, which is why it can check a key
before the workflow has one.

**Why the app user is not in the credential.** A credential is fixed for a node, but the app user changes with
every item; one workflow can serve thousands of Telegram users. So the app user is a field on the node
(section 5), filled per item, usually by an expression.

## 5. The node's fields

File: `nodes/Alexein/fields.ts`. Every field shown depends on the operation chosen
(`displayOptions.show.operation`).

**Always shown:**

| Field     | Internal name | What it is                                                                                                                                 |
| --------- | ------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Resource  | `resource`    | Always "Memory". n8n's convention is a Resource, then an Operation; it also gives the AI tool its name, such as "Search memory in Alexein" |
| Operation | `operation`   | One of the 20 below. It can't be an expression (`noDataExpression`), so one node runs one operation                                        |
| App User  | `user`        | Required, but hidden on List App Users. Your ID for the person whose memory this is, for example `{{ $json.message.from.id }}`             |

**Operation-specific fields.** An operation's internal value is the route it calls, but for `openItems`
(`open_items`) and `deleteUser` (`users/delete`).

| Operation (value)                   | Fields (internal names)                                                                                                                                                                                                                                                                                                                         |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Add (`add`)                         | Text `text` (required); Kind `kind`: message / note / document, default message; Wait Until Searchable `wait`; Redact `redact`; Additional Fields `additionalFields`: About `about` (comma list), Author `author`, Expires `expires`, Item ID `id`, Metadata `metadata` (JSON object), Role `role`, Session `session`, Title `title`, When `at` |
| Search (`search`)                   | Query `query` (required); Fast `fast`; Options `searchOptions`: After `after`, Before `before`, Context Length `contextLength` (default 4000, minimum 200), Filters `filters` (JSON), Kind `kind` (comma list), Provider `provider`, Source `source`                                                                                            |
| Get History (`history`)             | Subject `subject` (required); Attribute `attribute`                                                                                                                                                                                                                                                                                             |
| Get Latest (`latest`)               | Limit `k` (1-50, default 10); Options `latestOptions`: After, Before, Filters, Kind, Place `place`, Provider, Source                                                                                                                                                                                                                            |
| Find Phrase (`grep`)                | Phrase `pattern` (required); Limit `limit` (1-50, default 50); Options `grepOptions`: Kind, Provider, Source                                                                                                                                                                                                                                    |
| Open (`open`)                       | Ref `ref` (required)                                                                                                                                                                                                                                                                                                                            |
| Get Surrounding Excerpts (`around`) | Ref `ref` (required); Width `width` (1-5, default 2)                                                                                                                                                                                                                                                                                            |
| Get Summary (`summary`)             | none                                                                                                                                                                                                                                                                                                                                            |
| Get Sources (`sources`)             | none                                                                                                                                                                                                                                                                                                                                            |
| Get Open Items (`openItems`)        | Limit `limit` (1-50, default 50); Options `openItemsOptions`: Kind, Mine Only `mine` (default on), Place, Provider, Within Days `withinDays`                                                                                                                                                                                                    |
| List Facts (`facts`)                | Return All `returnAll`; Limit `limit` (1-100, default 50) and Cursor `cursor`, without Return All                                                                                                                                                                                                                                               |
| List Items (`items`)                | Return All; Limit (1-200, default 50) and Cursor; Options `itemsOptions`: Filters                                                                                                                                                                                                                                                               |
| Get Item (`item`)                   | Item ID `itemId` (required)                                                                                                                                                                                                                                                                                                                     |
| Get Status (`status`)               | Item IDs `ids` (required, comma list, up to 500)                                                                                                                                                                                                                                                                                                |
| Get Versions (`versions`)           | Item ID `itemId` (required)                                                                                                                                                                                                                                                                                                                     |
| Forget (`forget`)                   | Item IDs `items`, Sessions `sessions`, Refs `refs` (comma lists; at least one)                                                                                                                                                                                                                                                                  |
| Correct (`correct`)                 | Ref `ref` (required, a fact's); Replacement `replacement`                                                                                                                                                                                                                                                                                       |
| Export (`export`)                   | Return All; Limit (1-500, default 50) and Cursor                                                                                                                                                                                                                                                                                                |
| List App Users (`users`)            | Return All; Limit (1-500, default 50) and Cursor. No App User                                                                                                                                                                                                                                                                                   |
| Delete App User (`deleteUser`)      | none but App User                                                                                                                                                                                                                                                                                                                               |

Date fields (When, Expires, After, Before) use n8n's date picker, which gives an ISO time such as
`2026-12-31T00:00:00`. The API reads the date part.

## 6. What happens when the node runs

File: `nodes/Alexein/Alexein.node.ts`. n8n calls `execute()` once per run, with all input items.

```text
execute()
  operation = the Operation field (read once; it can't differ per item)
  if operation == add: added()     else: answered(operation)
  return one output list
```

### Every operation except Add: `answered()`

```text
for each input item i, in order:
  user    = checkedUser(App User of item i)        refused here if not a usable ID; none for List App Users
  request = request(operation, the fields of item i) → { route, body }
  answer  = send(route, body, user)                one HTTP request; with Return All, one per page,
                                                   following `next`, merged into one answer
  output  = shaped(operation, answer)              for Search, { context, ...answer }; else the answer
  emit { json: output, pairedItem: i }
on an error in item i: Continue On Fail → emit { error: message } for i and go on; otherwise stop the run
```

So 10 input items make 10 requests (more with Return All), one after the other, and 10 output items, each paired
with its input (n8n uses `pairedItem` to link outputs back to inputs).

### Add: `added()`

Add groups items so a batch of messages costs a few requests, not one per message:

```text
1. for each input item i:
     user = checkedUser(App User of i); wait = Wait Until Searchable of i; redact = Redact of i
     item = item(fields of i)          builds { text, kind, id, session, ... } with empty fields left out
     put (i, item) in the group for (user, wait, redact)
     on an error: Continue On Fail → error output for i; otherwise stop
2. for each group, in the order groups first appeared:
     split into batches of at most 500 items
     each batch → one POST /v2/memory/add { items: [...], wait, redact? }
                  with X-Alexein-User: user and Idempotency-Key: <key>-<batch index>
     the API answers with one entry per item, in the same order
     output for each input i = { ...its entry, waiting }
     on an error: every item in that batch gets it (Continue On Fail) or the run stops
3. emit the outputs in input order (failed items included, as errors, when Continue On Fail is on)
```

**Example.** With five input items for users `dana, sam, dana, dana, sam`, Wait and Redact off, the node makes
two requests: one for dana with items 1, 3 and 4, and one for sam with items 2 and 5. It then emits five outputs
in the original order 1 to 5.

**The Idempotency-Key** is a SHA-256 of the execution's ID, the node, the app user and the request body, then
`-<batch index>`. n8n's **Retry On Fail** runs the node again in the same execution, so a retried add sends the
same key, and the API takes it as the same items again rather than new ones: a retry never saves twice. The next
execution has another ID, so the same text sent again later is a new add. (The SDKs use one random UUID per call,
which serves a client that retries inside one call; here the retry is n8n's.)

### Sending: `send()`

Every request goes through n8n's `this.helpers.httpRequestWithAuthentication('alexeinApi', …)`. n8n adds the
`Authorization` header from the credential, so the node never touches the key itself.

```text
POST <Base URL as the host>/v2/memory/<route>
Authorization: Bearer tm_...          added by n8n from the credential
X-Alexein-User: <app user>            on every route but users
Idempotency-Key: <key>-<n>            on add
Content-Type: application/json
<body as JSON>
```

The node asks n8n for the full response and to not throw on HTTP errors (`returnFullResponse`,
`ignoreHttpStatusErrors`). It then checks the status itself, so it can report the API's own message (section 9).

### What the node does not do

- **It never retries.** Use the node's **Settings > Retry On Fail**; the Idempotency-Key makes that safe for Add.
- **It caches nothing** and keeps no state between runs.

## 7. Each operation, as sent and as returned

Unset optional fields are left out of the body (`present()` in `requests.ts`), so the API's own defaults apply.
The answers are the API's v2 shapes; the [API reference](https://docs.alexein.ai/api) has every field.

| Operation                | Route          | Body sent                                                                                                             | Output item                                                                  |
| ------------------------ | -------------- | --------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Add                      | `add`          | `{ items: [{ text, kind, id?, session?, role?, author?, title?, about?, at?, expires?, metadata? }], wait, redact? }` | one per input: `{ id, status: stored / queued, redacted?, waiting }`         |
| Search                   | `search`       | `{ query, fast, before?, after?, filters?, provider?, source?, kind? }`                                               | `{ context, query, answerable, notes, memories, sources? }`                  |
| Get History              | `history`      | `{ subject, attribute? }`                                                                                             | `{ subject, values: [{ attribute, value, since, negated }], suggestions? }`  |
| Get Latest               | `latest`       | `{ k, place?, after?, before?, filters?, provider?, source?, kind? }`                                                 | `{ memories, places? }`                                                      |
| Find Phrase              | `grep`         | `{ pattern, limit, provider?, source?, kind? }`                                                                       | `{ pattern, total, memories }`                                               |
| Open                     | `open`         | `{ ref }`                                                                                                             | `{ memory }`, and for a fact `sources`: the excerpts it was learned from     |
| Get Surrounding Excerpts | `around`       | `{ ref, width }`                                                                                                      | `{ memories }`                                                               |
| Get Summary              | `summary`      | `{}`                                                                                                                  | `{ items, first, last, sources, known }`                                     |
| Get Sources              | `sources`      | `{}`                                                                                                                  | `{ sources }`                                                                |
| Get Open Items           | `open_items`   | `{ limit, mine?, within_days?, place?, provider?, kind? }`                                                            | `{ items: [{ ref, text, date, added_at, age_days }], follow_ups }`           |
| List Facts               | `facts`        | `{ limit, cursor? }`                                                                                                  | `{ facts: [{ type, ref, text, source, date }], next }`                       |
| List Items               | `items`        | `{ limit, cursor?, filters? }`                                                                                        | `{ items: [ the item as added, and status ], next }`                         |
| Get Item                 | `item`         | `{ id }`                                                                                                              | `{ found, item? }`                                                           |
| Get Status               | `status`       | `{ items: [...] }`                                                                                                    | `{ items: [{ id, status: queued / stored / processed / unknown, reason }] }` |
| Get Versions             | `versions`     | `{ id }`                                                                                                              | `{ id, state, history }`                                                     |
| Forget                   | `forget`       | `{ items?, sessions?, refs? }` (at least one)                                                                         | `{ erased: { items, facts, versions, waiting, relearning }, complete }`      |
| Correct                  | `correct`      | `{ ref, replacement? }`                                                                                               | `{ retracted, text, replacement }`                                           |
| Export                   | `export`       | `{ limit, cursor? }`                                                                                                  | `{ user, exported_at, records, next, withheld }`                             |
| List App Users           | `users`        | `{ limit, cursor? }`                                                                                                  | `{ users: [{ user, items, facts, last_write }], next }`                      |
| Delete App User          | `users/delete` | `{}`                                                                                                                  | the API's receipt                                                            |

**Memories** (search, grep, latest, around, open) are `{ type: known, text }`, `{ type: fact, ref, text, source }`
or `{ type: excerpt, ref, text, date, added_at, session, roles }`. A ref is opaque: pass it back to Open, Get
Surrounding Excerpts, Correct or Forget, and never parse it.

**Paged operations with Return All** ask for the longest page the API allows (facts 100, items 200, export and
users 500) and follow `next` until it is null. The output is the first page's fields with every page's list
(`facts`, `items`, `records` or `users`) and `next: null`.

**About Add's answer:** `stored` is searchable now; `queued` is searchable in a moment, and `waiting` counts the
items not yet searchable. With Wait Until Searchable on, the API waits briefly for them, so `waiting` is usually 0.

**About Search's answer:** `answerable` is false when memory does not seem to hold the answer, and null when it
was not checked: with Fast, or a search narrowed by After, Filters, Provider, Source or Kind.

## 8. The search context

`context()` in `requests.ts` builds one block of text from a search answer, ready to paste into a prompt:

```text
<each note, on a line>
- Alice Chen · home city: Lisbon (said 2026-10-01)
- (said 2026-10-01) Alice lives in Lisbon
- 2026-10-01: I just moved to Lisbon from Berlin for the new job at Acme.
```

- **Order:** the notes, then the memories in the order the API gave them: known lines, facts, excerpts.
- **Excerpts** are prefixed with their date (the day of `date`) when known.
- **Whitespace:** each line's whitespace is collapsed, so an excerpt becomes one line.
- **Length:** whole lines only. When the next line would pass Context Length (default 4,000 characters), it stops
  there, so the block never ends mid-sentence.
- **Empty** when memory found nothing, notes or not.
- **Same as the SDKs:** it is the text `SearchResult.context()` gives in `alexein` and `@alexein/sdk`
  (`docs/DESIGN.md`), so a prompt reads the same from either.

## 9. Errors

| Where it fails                                | What n8n shows                                                                                                                                                                                                                                   |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| App User is not a usable ID                   | `App User "dana smith" is not a usable ID: 1 to 35 letters, digits, '.', '_' and '-', beginning with a letter or digit`. No request is made                                                                                                      |
| Add with empty Text                           | `Text is empty: there is nothing to remember`                                                                                                                                                                                                    |
| Metadata or Filters that isn't a JSON object  | `Metadata must be a JSON object` / `Filters must be a JSON object`                                                                                                                                                                               |
| Forget naming nothing; Get Status with no IDs | `Nothing to forget: ...` / `Item IDs is empty: ...`                                                                                                                                                                                              |
| The API answers 400-599                       | A `NodeApiError` whose message is the API's `detail`, for example `memory holds nothing by this ref` (404). For a 422, the description names each field from the API's `errors`. For a 429 or 503, the description says to turn on Retry On Fail |
| The API can't be reached                      | n8n's own connection error                                                                                                                                                                                                                       |

**Common API answers:**

| Status | Meaning                                                                                            |
| ------ | -------------------------------------------------------------------------------------------------- |
| 400    | `X-Alexein-User` is missing or not a usable id                                                     |
| 401    | the key isn't one the API issued                                                                   |
| 403    | the key reads only, and the operation writes (Add, Forget, Correct, Get Versions, Delete App User) |
| 404    | a read for an app user nothing was ever written for, or a ref memory does not hold                 |
| 413    | the body is over 1,000,000 bytes                                                                   |
| 422    | a field is missing or out of bounds                                                                |
| 429    | too many requests in flight, or reads too fast                                                     |
| 503    | the service is busy or briefly unavailable                                                         |

Search, Get Summary, List Facts and Get Versions answer an app user with nothing saved with `200`, empty; the other
reads answer `404`.

**Continue On Fail** (node Settings) turns an error into an output item `{ "error": "<message>" }` for that input
item, and the rest carry on. Without it, the first error stops the workflow. As an agent tool, n8n reports a failed
tool call to the agent; turning on Continue On Fail on the tool node makes the error an ordinary result the model
reads.

## 10. As an AI Agent tool

Because the node sets `usableAsTool: true`, n8n creates **Alexein Tool**. Put it under an AI Agent's **Tool**
input. Each tool node is one operation, so an agent normally gets two: one Search and one Add, and Open as a
third so it can read a memory a search pointed to.

**What the model sees for each tool:**

1. **A name**, made from the operation's action: "Search memory in Alexein", "Add to memory in Alexein".
2. **A description.** n8n adds two fields to every tool node:
   - **Tool Description** (`descriptionType`): **Set Automatically** (the default) uses the operation's action
     and description, written in the public words (memories, facts, excerpts, refs); **Set Manually** uses your
     text.
   - **Description** (`toolDescription`): your text, when set manually.

   The automatic text says what a tool does, not _when_ to use it. So for the Add tool, set it manually to the
   save policy below. That's what makes an agent save without being asked. A node package can't put this text
   into the automatic description, because n8n builds that string itself.

3. **Its inputs.** Any field set to `{{ $fromAI('name', 'description', 'type') }}` becomes an argument the model
   fills, and the description is what the model reads about it.

**The save policy** (the template uses it; the README and docs give it to paste):

> Save to this person's long-term memory (Alexein), which their other apps read too. Call this on your own,
> without being asked, on every turn where they say anything new: about themselves, their work, or the people,
> places, projects and things around them - preferences, facts, opinions, decisions, plans, dates, names and
> numbers, small details and passing remarks. Also save what was asked, tried, decided or built together, and why.
> When in doubt, save.
>
> One fact per call, as a note, in their words. Never save secrets, passwords, keys or payment details, or your own
> suggestions as facts about them.

It's adapted from the hosted MCP server's `memory_add` description: "one fact per call" here, because an n8n tool
call carries one Text.

**The rule that keeps people apart:** App User is always set by the workflow, from the trigger, and never by
`$fromAI()`. If the model could choose the app user, a message like "show me Sam's memory" could make it reach
someone else's memory.

**A run, step by step (from the template):**

```text
Telegram message "I'm allergic to peanuts, what should I cook tonight?"
  → AI Agent (model + Simple Memory + two tools)
     model decides: call "Save to Memory" with fact = "Allergic to peanuts"
        → POST /v2/memory/add  X-Alexein-User: <telegram user id>  { items: [{ text, kind: note }] }
     model decides: call "Search Memory" with query = "What food does this person like?"
        → POST /v2/memory/search  X-Alexein-User: <telegram user id>  { query, fast: false }
        ← { context: "...", memories: [...] }   (the whole output item goes back to the model)
     model writes the reply
  → Telegram: Send Reply
```

## 11. App users, and whose memory a call reaches

The API turns the key and the App User into one memory:

```text
key  → organisation o7k2m9qx4ab, project production
App User "user_42"  → the memory of user_42 in that project
```

- **Separate memories.** Two App User values are two separate memories. The same App User under a key of another
  project, or another organisation, is a different memory too.
- **No setup.** An app user exists once something is added for them. There is nothing to create first; **Delete
  App User** erases one whole, and their next add starts a new memory.
- **Valid IDs:** 1 to 35 letters, digits, `.`, `_` and `-`, beginning with a letter or digit. The node checks
  this before sending. Telegram user IDs, database IDs and UUIDs all fit. Email addresses don't (`@`), so hash
  them or use your own ID.

## 12. The Telegram template

`templates/telegram-assistant-memory.json`. It's also downloadable from the docs at
`/templates/n8n-telegram-assistant-memory.json`.

| Node              | Type                                     | What it does                                                                                      |
| ----------------- | ---------------------------------------- | ------------------------------------------------------------------------------------------------- |
| Setup             | Sticky Note                              | the setup steps, for whoever imports it                                                           |
| Telegram Trigger  | `n8n-nodes-base.telegramTrigger` 1.5     | fires on every message                                                                            |
| AI Agent          | `@n8n/n8n-nodes-langchain.agent` 3.1     | prompt = the message text; its system message says to search before answering and save what's new |
| OpenAI Chat Model | `lmChatOpenAi` 1.3, model `gpt-5-mini`   | the model (your OpenAI key; paid by you)                                                          |
| Simple Memory     | `memoryBufferWindow` 1.4                 | the last 10 messages of this chat, keyed by chat ID: short-term                                   |
| Search Memory     | `@alexein/n8n-nodes-alexein.alexeinTool` | Search, App User = Telegram user ID, query from `$fromAI`, description set manually               |
| Save to Memory    | `@alexein/n8n-nodes-alexein.alexeinTool` | Add, kind note, App User = Telegram user ID, text from `$fromAI`, description = the save policy   |
| Send Reply        | `n8n-nodes-base.telegram` 1.2            | sends the agent's answer back to the chat                                                         |

Short-term memory (Simple Memory) and long-term memory (Alexein) are separate on purpose:

- **Simple Memory** carries the current conversation.
- **Alexein** carries what the person said days or months ago, and what other apps saved for them.

## 13. MCP instead of the node

Alexein also runs a hosted MCP server at `https://api.alexein.ai/v1/mcp`. n8n's **MCP Client Tool** (for agents)
and **MCP Client** (a normal node) can use it instead of this node:

|            | This node                                        | n8n's MCP Client                                                                 |
| ---------- | ------------------------------------------------ | -------------------------------------------------------------------------------- |
| App user   | per item, from an expression                     | fixed in the credential (Multiple Headers); with OAuth, your own personal memory |
| Auth       | Alexein API credential                           | Multiple Headers Auth (`Authorization` + `X-Alexein-User`) or MCP OAuth2         |
| Operations | all 20, including writes like Forget and Correct | the MCP tools: the reads, plus `memory_add` for a key or sign-in that writes     |
| Best for   | workflows serving many people                    | one person's agent                                                               |

Tested: n8n's MCP Client with Multiple Headers Auth reaches `/v1/mcp` and `memory_grep` finds that app user's
items. Not tested: MCP OAuth2 from n8n.

## 14. Every variable and setting

### In the node itself: none from the environment

The node reads **no environment variables and no files**. n8n's rules for verified nodes forbid both, and its lint
enforces it. Everything comes from:

- **The credential:** `apiKey` and `baseUrl` (section 4).
- **The node's fields:** section 5.

### n8n's own settings that change how it behaves

| Where           | Setting                                                         | Effect                                                                         |
| --------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Node > Settings | Retry On Fail, Max Tries, Wait Between Tries                    | retries a failed run; use it for 429 and 503                                   |
| Node > Settings | Continue On Fail (On Error: Continue)                           | a failed item becomes `{ error }` instead of stopping the run                  |
| Node > Settings | Always Output Data                                              | outputs an empty item when there is nothing to output                          |
| Tool node       | Tool Description: Set Automatically / Set Manually, Description | what the model is told (section 10)                                            |
| n8n server      | `N8N_COMMUNITY_PACKAGES_ENABLED`                                | must not be `false`, or community nodes can't be installed                     |
| n8n server      | `N8N_COMMUNITY_PACKAGES_ALLOW_TOOL_USAGE`                       | not needed in n8n 2.x; older n8n needed it `true` for community nodes as tools |

### In the e2e test (`e2e/run.mjs`, development only)

| Variable          | Default                 | Meaning                                                                                           |
| ----------------- | ----------------------- | ------------------------------------------------------------------------------------------------- |
| `ALEXEIN_API_KEY` | required                | a key that writes, for the API under test                                                         |
| `ALEXEIN_API_URL` | `http://localhost:8210` | the API as your machine reaches it; n8n in Docker reaches the same port at `host.docker.internal` |
| `N8N_PORT`        | `5679`                  | where the test's n8n listens                                                                      |

`e2e/docker-compose.yml` runs n8n 2.44.6 with `N8N_DIAGNOSTICS_ENABLED=false`, `N8N_PERSONALIZATION_ENABLED=false`
and `N8N_SECURE_COOKIE=false` (for plain-HTTP localhost). It logs in as `e2e@example.com` /
`E2e-test-password-1`, a local throwaway owner.

### In CI and publishing (`.github/workflows/n8n-ci.yml`, `n8n-publish.yml` at the repository root)

| Variable                | Where                           | Meaning                                                                                                                              |
| ----------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `NPM_TOKEN`             | repo secret                     | an npm token for the first publish; remove it once the trusted publisher is set                                                      |
| `GITHUB_REF_NAME`       | set by GitHub                   | the tag; must be `n8n-v<version from package.json>`                                                                                  |
| `GITHUB_ACTIONS`        | set by GitHub                   | makes `n8n-node release` publish (lint, build, `npm publish`) instead of starting the local release-it flow                          |
| `RELEASE_MODE`          | set by `n8n-node release`       | lets `npm publish` past the package's `prepublishOnly` guard. Set it yourself (`RELEASE_MODE=true`) only to publish from your laptop |
| `NPM_CONFIG_PROVENANCE` | set by `n8n-node release` in CI | attaches the provenance statement n8n requires                                                                                       |

## 15. Limits

| Limit                 | Value                                                             | Where        | What happens                                                                 |
| --------------------- | ----------------------------------------------------------------- | ------------ | ---------------------------------------------------------------------------- |
| Items per add request | 500                                                               | API          | the node splits larger groups itself                                         |
| Request body          | 1,000,000 bytes                                                   | API          | `413`; 500 long documents can pass it, so send big documents in smaller runs |
| Query, phrase         | 2,000 characters                                                  | API          | `422`                                                                        |
| App user ID           | 35 characters                                                     | node and API | refused before sending                                                       |
| Kind                  | up to 8                                                           | API          | `422`                                                                        |
| Results               | Latest, Find Phrase and Open Items 50; Width 5; pages 100 to 500  | node and API | the field won't go higher                                                    |
| Context               | Context Length, minimum 200, default 4,000 characters             | node         | whole lines only                                                             |
| Rate                  | see [Limits](https://docs.alexein.ai/concepts/limits#rate-limits) | API          | `429`, with `Retry-After`                                                    |

The node sends one request at a time. A fast loop of many reads for the same app user can still hit the rate
limit; Retry On Fail handles that.

## 16. Why it is built this way

- **Programmatic, not declarative.** n8n prefers declarative nodes for plain REST APIs. Three things here need
  code:
  - Add grouping items across inputs into one request, with an Idempotency-Key.
  - Search building `context` from the whole answer.
  - Return All following `next` from page to page.
- **No runtime dependencies.** n8n won't verify a node that has any. HTTP goes through n8n's helper, and the
  context builder is written in the package rather than taken from `@alexein/sdk`.
- **The app user is a field, not part of the credential,** so one workflow serves many people and the model can
  never choose it.
- **One node with an Operation field** rather than 20 nodes. That's n8n's convention, and it gives the AI tool
  readable names.
- **No `.d.ts` files in the build.** n8n's verification scanner reads `AlexeinApi.credentials.d.ts` as a wrongly
  named credential and fails the package.

## 17. Tests

| Command            | What it checks                                                                                                                                                                                                                                                                                                                                                                                  | Needs                           |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| `npm test`         | builds, then 23 unit tests: every operation's route and body, and each against `contract/openapi.json`; item building, ID checks, the base URL as the host, the context text, Add batching (1,201 → 500/500/201, users and options split, outputs in order), Idempotency-Keys, Return All, the headers per route, API errors, Continue On Fail, the names saved workflows use, the public words | nothing                         |
| `npm run lint`     | n8n's community-node rules (the same ones verification uses)                                                                                                                                                                                                                                                                                                                                    | nothing                         |
| `node e2e/run.mjs` | real n8n 2.44.6 in Docker against an Alexein API (section 14)                                                                                                                                                                                                                                                                                                                                   | Docker, a running API and a key |

The end-to-end test checks:

- n8n loads the node and its tool variant, and the tool has a manual Description.
- The credential Test passes.
- Webhook → Add (wait) → fast Search (the context holds the item) → reply → Forget, and the API then reports the
  item `forgotten`.
- n8n's MCP Client reaches `/v1/mcp` with headers.
- The Telegram template imports, and every node version in it exists.
