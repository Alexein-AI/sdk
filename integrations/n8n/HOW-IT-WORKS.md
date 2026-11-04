# How the Twin Memory n8n node works

This explains `n8n-nodes-twinmemory` from end to end. It covers what n8n loads, what each file does, what goes over
the wire, how an AI Agent uses the node, and every setting and variable involved. For testing and publishing, see
[TESTING-AND-PUBLISHING.md](TESTING-AND-PUBLISHING.md).

Version 0.1.0, tested with n8n 2.44.6.

This is a note for whoever works on the node, and it is not published: it describes the engine and the local
stack. What users read is the README and https://docs.alexein.ai/integrations/n8n.

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
11. [End users, and whose memory a call reaches](#11-end-users-and-whose-memory-a-call-reaches)
12. [The Telegram template](#12-the-telegram-template)
13. [MCP instead of the node](#13-mcp-instead-of-the-node)
14. [Every variable and setting](#14-every-variable-and-setting)
15. [Limits](#15-limits)
16. [Why it is built this way](#16-why-it-is-built-this-way)
17. [Tests](#17-tests)

---

## 1. The whole picture

```text
 n8n workflow                                             twin memory API (twin-memory repo)
 ─────────────────────────────────────────────            ───────────────────────────────────
 [Trigger] ──► [Twin Memory: Add] ──► [Twin Memory: Search] ──► ...
                     │                        │
                     │  POST /v1/memory/add    │  POST /v1/memory/search
                     │  Authorization: Bearer tm_...   (from the credential)
                     │  X-Twin-Account: user_42        (from the End User field)
                     ▼                        ▼
               ┌──────────────────────────────────────────┐
               │ key → organisation + project              │
               │ account = <org>.<project>.<end user>      │
               │ one SQLite file per account               │
               └──────────────────────────────────────────┘
```

The node is a thin client. It turns n8n parameters into HTTP requests to the twin memory API, and turns the
answers back into n8n items. It holds no memory itself and no state between runs. All storage, search and
ranking happen in the API.

It is used in two ways:

- **As a normal node** in a workflow: one request per input item (Add groups them; see section 6).
- **As an AI Agent tool:** n8n makes a copy of it, "Twin Memory Tool", which an agent can call. The model fills
  in some fields, such as the search question (section 10).

## 2. The files

```text
packages/n8n/
├── package.json                       the npm package; its "n8n" field tells n8n what to load
├── credentials/
│   └── TwinMemoryApi.credentials.ts   the "Twin Memory API" credential: key, base URL, test
├── nodes/TwinMemory/
│   ├── TwinMemory.node.ts             the node: its description, and execute() that sends requests
│   ├── fields.ts                      every field the user sees: resource, operation, end user, ...
│   ├── requests.ts                    pure functions: parameters → request; the search context
│   └── TwinMemory.node.json           "codex": categories and documentation links for n8n's panel
├── icons/                             twinmemory.svg (light) and twinmemory.dark.svg (dark)
├── templates/telegram-assistant-memory.json   the Telegram assistant workflow
├── test/                              unit tests, run with Node's own test runner against dist/
├── e2e/                               real n8n in Docker against a memory API
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
  "credentials": ["dist/credentials/TwinMemoryApi.credentials.js"],
  "nodes": ["dist/nodes/TwinMemory/TwinMemory.node.js"]
}
```

- **The keyword** is how npm search and n8n recognise a community node package.
- **`n8nNodesApiVersion: 1`** is the node API version this package is written against.
- **`strict: true`** opts in to n8n's stricter checks. They're required for verification.
- **`credentials` and `nodes`** are the compiled files n8n loads.

**Where it lives in n8n:**
- **Installed from the UI** (Settings > Community Nodes): the package goes to `~/.n8n/nodes/node_modules/` and
  the node type is `n8n-nodes-twinmemory.twinMemory`.
- **Linked during development** (`npm run dev`, or the e2e test): it goes to `~/.n8n/custom/node_modules/` and
  n8n names it `CUSTOM.twinMemory`.

For every node with `usableAsTool: true`, n8n also creates a second type with `Tool` added to the name, such as
`n8n-nodes-twinmemory.twinMemoryTool`. That is the "Twin Memory Tool" an AI Agent sees.

## 4. The credential

File: `credentials/TwinMemoryApi.credentials.ts`. n8n shows it as **Twin Memory API**; its internal name is
`twinMemoryApi`.

| Field      | Internal name | Required | Default                      | Stored encrypted |
| ---------- | ------------- | -------- | ---------------------------- | ---------------- |
| API Key    | `apiKey`      | yes      | (empty)                      | yes (password field) |
| Base URL   | `baseUrl`     | yes      | `https://api.alexein.ai`     | yes (n8n encrypts every credential) |

**How it signs requests.** The `authenticate` block tells n8n to add one header to every request the node
makes through `httpRequestWithAuthentication`:

```text
Authorization: Bearer <apiKey>
```

**How the Test button works.** The `test` block makes n8n send:

```text
GET <baseUrl without trailing slashes>/v1/me
Authorization: Bearer <apiKey>
```

A `200` shows "Connection successful". The API answers `/v1/me` with what the key is, for example
`{"kind": "key", "org": "o7k2…", "project": "production", "key_id": "key_…", "writes": true}`. A `401` (a key
the API didn't issue) shows as a failed test. `/v1/me` names no end user, which is why it can check a key
before the workflow has one.

**Why the end user is not in the credential.** A credential is fixed for a node, but the end user changes with
every item; one workflow can serve thousands of Telegram users. So the end user is a field on the node
(section 5), filled per item, usually by an expression.

## 5. The node's fields

File: `nodes/TwinMemory/fields.ts`. Every field shown depends on the operation chosen
(`displayOptions.show.operation`).

**Always shown:**

| Field      | Internal name | What it is |
| ---------- | ------------- | ---------- |
| Resource   | `resource`    | Always "Memory". n8n's convention is a Resource, then an Operation; it also gives the AI tool its name, such as "Search memory in Twin Memory" |
| Operation  | `operation`   | One of the 14 below. It can't be an expression (`noDataExpression`), so one node runs one operation |
| End User   | `endUser`     | Required. Your ID for the person whose memory this is, for example `{{ $json.message.from.id }}` |

**Operation-specific fields** (the operation's internal value is the API route it calls):

| Operation (value)                     | Fields (internal names)                                                                 |
| ------------------------------------- | --------------------------------------------------------------------------------------- |
| Add (`add`)                           | Text `text` (required); Kind `kind`: message / note / document, default message; Wait Until Searchable `wait`; Additional Fields `additionalFields`: About `about` (comma list), Author `author`, Expires `expires`, Item ID `id`, Metadata `metadata` (JSON object), Role `role`, Session `session`, Title `title`, When `at` |
| Search (`search`)                     | Query `query` (required); Fast `fast`; Options `searchOptions`: After `after`, Before `before`, Context Length `contextLength` (default 4000, minimum 200), Scope `scope` |
| Get History (`history`)               | Subject `subject` (required); Attribute `attribute` |
| Get Latest (`latest`)                 | Limit `k` (1-50, default 10); Options `latestOptions`: After `after`, Before `before`, Place `place` |
| Find Phrase (`grep`)                  | Phrase `pattern` (required); Limit `limit` (1-50, default 50); Scope `scope` |
| Read (`read`)                         | Path `path` (required) |
| List (`ls`)                           | Path `path` (empty = the top) |
| Get Surrounding Passages (`around`)   | Passage ID `passageId` (required); Width `width` (1-5, default 2) |
| Get Overview (`overview`)             | none |
| Get Versions (`versions`)             | Item ID `itemId` (required) |
| Get Status (`status`)                 | IDs `ids` (required, comma list, up to 500) |
| Get Lineage (`lineage`)               | ID `lineageId` (required): an item ID, an event ID `ev_…`, or a fact ID `th_…#r…` |
| Forget (`forget`)                     | Item IDs `items`, Sessions `sessions`, Threads `threads`, Events `events` (comma lists; at least one) |
| Correct (`correct`)                   | Fact ID `recordId` (required); Replacement `replacement` |

Date fields (When, Expires, After, Before) use n8n's date picker, which gives an ISO time such as
`2026-12-31T00:00:00`. The API reads the date part.

## 6. What happens when the node runs

File: `nodes/TwinMemory/TwinMemory.node.ts`. n8n calls `execute()` once per run, with all input items.

```text
execute()
  operation = the Operation field (read once; it can't differ per item)
  if operation == add: added()     else: answered(operation)
  return one output list
```

### Every operation except Add: `answered()`

```text
for each input item i, in order:
  user    = checkedUser(End User of item i)        refused here if not a usable ID
  request = request(operation, the fields of item i) → { route, body }
  answer  = send(route, body, user)                one HTTP request
  output  = shaped(operation, answer)              for Search, { context, ...answer }; else the answer
  emit { json: output, pairedItem: i }
on an error in item i: Continue On Fail → emit { error: message } for i and go on; otherwise stop the run
```

So 10 input items make 10 requests, one after the other, and 10 output items, each paired with its input (n8n
uses `pairedItem` to link outputs back to inputs).

### Add: `added()`

Add groups items so a batch of messages costs a few requests, not one per message:

```text
1. for each input item i:
     user = checkedUser(End User of i); wait = Wait Until Searchable of i
     item = item(fields of i)          builds { text, kind, id, session, ... } with empty fields left out
     put (i, item) in the group for (user, wait)
     on an error: Continue On Fail → error output for i; otherwise stop
2. for each group, in the order groups first appeared:
     split into batches of at most 500 items
     each batch → one POST /v1/memory/add { items: [...], wait } with X-Twin-Account: user
     the API answers with one entry per item, in the same order
     output for each input i = { ...its entry, pending, queued }
     on an error: every item in that batch gets it (Continue On Fail) or the run stops
3. emit the outputs in input order (failed items included, as errors, when Continue On Fail is on)
```

**Example.** With five input items for users `dana, sam, dana, dana, sam` and Wait off, the node makes two
requests: one for dana with items 1, 3 and 4, and one for sam with items 2 and 5. It then emits five outputs in
the original order 1 to 5.

### Sending: `send()`

Every request goes through n8n's `this.helpers.httpRequestWithAuthentication('twinMemoryApi', …)`. n8n adds
the `Authorization` header from the credential, so the node never touches the key itself.

```text
POST <baseUrl, trailing slashes removed>/v1/memory/<route>
Authorization: Bearer tm_...          added by n8n from the credential
X-Twin-Account: <end user>
Content-Type: application/json
<body as JSON>
```

The node asks n8n for the full response and to not throw on HTTP errors (`returnFullResponse`,
`ignoreHttpStatusErrors`). It then checks the status itself, so it can report the API's own message (section 9).

### What the node does not do

- **It never retries.** n8n's community-node rules forbid timers, so there is no sleeping between attempts. Use
  the node's **Settings > Retry On Fail**.
- **It sends no Idempotency-Key.** That key only helps a client that retries the same request itself. To make
  repeated adds safe, set **Item ID**: the same ID again is the same item (an edit, if the text differs) rather
  than a copy.
- **It caches nothing** and keeps no state between runs.

## 7. Each operation, as sent and as returned

Unset optional fields are left out of the body (`present()` in `requests.ts`), so the API's own defaults apply.

| Operation    | Body sent                                                        | Output item |
| ------------ | ---------------------------------------------------------------- | ----------- |
| Add          | `{ items: [{ text, kind, id?, session?, role?, author?, title?, about?, at?, expires?, metadata? }], wait }` | one per input: `{ id, event_id, thread_id?, path?, landed?, pending, queued }` |
| Search       | `{ query, fast, before?, after?, scope? }`                         | `{ context, query, found, known?, worked_out?, notes?, facts?, hits, held?, filtered }` |
| Get History  | `{ subject, attribute? }`                                          | `{ subject, count, assertions }`, or `{ subject, error, subjects }` when nothing is recorded |
| Get Latest   | `{ k, place?, after?, before? }`                                    | `{ place, window, found, passages }` |
| Find Phrase  | `{ pattern, limit, scope? }`                                        | `{ pattern, total, matches }` |
| Read         | `{ path }`                                                         | `{ path, text }`, or `{ path, error, siblings }` |
| List         | `{ path }`                                                         | `{ path, entries }` |
| Get Surrounding Passages | `{ passage_id, width }`                                | `{ of, passages }` |
| Get Overview | `{}`                                                               | `{ directories, manifest, index }` |
| Get Versions | `{ id }`                                                           | `{ id, state, history }` |
| Get Status   | `{ ids: [...] }`                                                   | `{ phases: { <id>: accepted / landed / read / folded / unknown } }` |
| Get Lineage  | `{ id }`                                                           | `{ of, events, passages, records, assertions, core }` |
| Forget       | `{ items?, sessions?, threads?, events? }` (at least one)          | the receipt: `{ events, tables: { <table>: { before, after } }, ... }` |
| Correct      | `{ record_id, replacement? }`                                      | `{ retracted, text, replacement }` |

**About Add's answer:**
- **With a queue** (the hosted service, or a local stack with Redis), the API accepts the items, answers `202`,
  and lands them a moment later. Each entry has `landed: true/false`, and `pending` counts those not landed yet.
- **With Wait Until Searchable on,** the API waits for them to land before answering, so `pending` is usually 0.
- **Without a queue** (a bare engine), items land as the API answers, so the entries carry `thread_id` and `path`
  and `pending` is 0.

**About Search's answer:**
- **`known`:** what is true now.
- **`facts`:** dated lines read from conversations, each with the passage it came from (`source`).
- **`hits`:** whole passages.
- **`held: false`:** memory judged it doesn't hold the answer.
- **`filtered`:** whether the model filter ran.
- **Fast:** skips that filter, so it's free and quicker, a little less precise, and `filtered` is false.

## 8. The search context

`context()` in `requests.ts` builds one block of text from a search answer, ready to paste into a prompt:

```text
What is known:
- Dana lives in Lisbon (since 2026-10-01).

Worked out:
- ...

Facts:
- 2026-10-01: Dana moved to Lisbon for a job at Acme.

Passages:
- **Dana** 00:00 · I moved to Lisbon for the job at Acme.
```

- **Order:** sections run from most to least distilled. Empty sections are left out.
- **Whitespace:** each line's whitespace is collapsed, so a passage becomes one line.
- **Length:** whole entries only. When the next entry would pass Context Length (default 4,000 characters), it
  stops there, so the block never ends mid-sentence.
- **Same as the SDK:** it is exactly the text of `SearchResult.context()` in the Python SDK (`twinmemory`), so a
  prompt reads the same from either. A test in each package checks the same example.

## 9. Errors

| Where it fails | What n8n shows |
| -------------- | -------------- |
| End User is not a usable ID | `End User "dana smith" is not a usable ID: letters, digits, '.', '_' and '-', starting with a letter or digit. Up to 35 characters always fits.` No request is made. The node refuses an ID over 64 characters itself; a shorter one can still be too long for the API, whose `400` states the maximum |
| Add with empty Text | `Text is empty: there is nothing to remember` |
| Metadata that isn't a JSON object | `Metadata must be a JSON object` |
| Forget naming nothing; Get Status with no IDs | `Nothing to forget: ...` / `IDs is empty: ...` |
| The API answers 400-599 | A `NodeApiError` whose message is the API's `detail`, for example `no memory for end user 'dana' yet` (404). For a 422, each field: `body.query: String should have at most 2000 characters`. For a 429 or 503, the description adds "Turn on Retry On Fail in the node settings to try again." |
| The API can't be reached | n8n's own connection error |

**Common API answers:**

| Status | Meaning |
| ------ | ------- |
| 401 | the key isn't one the API issued |
| 403 | the key reads only, and the operation writes (Add, Forget, Correct) |
| 404 | nothing was ever added for this end user, or no such record |
| 413 | the body is over a megabyte |
| 429 | too many requests for this end user right now |
| 503 | the end user's memory is being rebuilt, or the service is at capacity |

**Continue On Fail** (node Settings) turns an error into an output item `{ "error": "<message>" }` for that input
item, and the rest carry on. Without it, the first error stops the workflow.

**A Search on a brand-new end user is a 404,** because nothing was ever added for them. In a workflow, either
add something first, or turn on Continue On Fail and treat the error as "no memory yet". As an agent tool, n8n
reports a failed tool call to the agent; what the model then sees is n8n's behaviour, not this node's, and
hasn't been tested yet. Turning on Continue On Fail on the tool node makes the error an ordinary result the
model reads.

## 10. As an AI Agent tool

Because the node sets `usableAsTool: true`, n8n creates **Twin Memory Tool**. Put it under an AI Agent's
**Tool** input. Each tool node is one operation, so an agent normally gets two: one Search and one Add.

**What the model sees for each tool:**

1. **A name**, made from the operation's action: "Search memory in Twin Memory", "Add to memory in Twin Memory".
2. **A description.** n8n adds two fields to every tool node:
   - **Tool Description** (`descriptionType`): **Set Automatically** (the default) uses the action text above;
     **Set Manually** uses your text.
   - **Description** (`toolDescription`): your text, when set manually.

   The automatic text is short and says nothing about *when* to use the tool. So for the Add tool, set it
   manually to the save policy below. That's what makes an agent save without being asked. A node package can't
   put this text into the automatic description, because n8n builds that string itself.
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

It's adapted from the hosted MCP server's `memory_add` description: "one fact per call" here, because an n8n
tool call carries one Text.

**The rule that keeps people apart:** End User is always set by the workflow, from the trigger, and never by
`$fromAI()`. If the model could choose the end user, a message like "show me Sam's memory" could make it reach
someone else's memory.

**A run, step by step (from the template):**

```text
Telegram message "I'm allergic to peanuts, what should I cook tonight?"
  → AI Agent (model + Simple Memory + two tools)
     model decides: call "Save to Memory" with fact = "Allergic to peanuts"
        → POST /v1/memory/add  X-Twin-Account: <telegram user id>  { items: [{ text, kind: note }] }
     model decides: call "Search Memory" with query = "What food does this person like?"
        → POST /v1/memory/search  X-Twin-Account: <telegram user id>  { query, fast: false }
        ← { context: "What is known: ...", ... }   (the whole output item goes back to the model)
     model writes the reply
  → Telegram: Send Reply
```

## 11. End users, and whose memory a call reaches

The API turns the key and the End User into one account:

```text
key  → organisation o7k2m9qx4ab, project production
End User "user_42"  → account o7k2m9qx4ab.production.user_42   (one SQLite file of its own)
```

- **Separate memories.** Two End User values are two separate memories. The same End User under a key of
  another project, or another organisation, is a different memory too.
- **No setup.** An end user exists once something is added for them. There is nothing to create first.
- **Valid IDs:** letters, digits, `.`, `_` and `-`, starting with a letter or digit. The node checks this before
  sending.
  - **Length:** the API also caps it at 64 characters minus the organisation and project prefix, usually about
    35. A longer one is refused by the API (400).
  - **Good choices:** Telegram user IDs, database IDs and UUIDs all fit. Email addresses don't (`@`), so hash
    them or use your own ID.

## 12. The Telegram template

`templates/telegram-assistant-memory.json`. It's also downloadable from the site at
`/templates/n8n-telegram-assistant-memory.json`.

| Node              | Type                                    | What it does |
| ----------------- | --------------------------------------- | ------------ |
| Setup             | Sticky Note                             | the setup steps, for whoever imports it |
| Telegram Trigger  | `n8n-nodes-base.telegramTrigger` 1.5    | fires on every message |
| AI Agent          | `@n8n/n8n-nodes-langchain.agent` 3.1    | prompt = the message text; its system message says to search before answering and save what's new |
| OpenAI Chat Model | `lmChatOpenAi` 1.3, model `gpt-5-mini`  | the model (your OpenAI key; paid by you) |
| Simple Memory     | `memoryBufferWindow` 1.4                | the last 10 messages of this chat, keyed by chat ID: short-term |
| Search Memory     | `n8n-nodes-twinmemory.twinMemoryTool`   | Search, End User = Telegram user ID, query from `$fromAI`, description set manually |
| Save to Memory    | `n8n-nodes-twinmemory.twinMemoryTool`   | Add, kind note, End User = Telegram user ID, text from `$fromAI`, description = the save policy |
| Send Reply        | `n8n-nodes-base.telegram` 1.2           | sends the agent's answer back to the chat |

Short-term memory (Simple Memory) and long-term memory (twin memory) are separate on purpose:

- **Simple Memory** carries the current conversation.
- **Twin memory** carries what the person said days or months ago, and what other apps saved for them.

## 13. MCP instead of the node

twin memory also runs a hosted MCP server at `/v1/mcp`. n8n's **MCP Client Tool** (for agents) and **MCP Client**
(a normal node) can use it instead of this node:

| | This node | n8n's MCP Client |
| --- | --- | --- |
| End user | per item, from an expression | fixed in the credential (Multiple Headers) or chosen at sign-in (OAuth) |
| Auth | Twin Memory API credential | Multiple Headers Auth (`Authorization` + `X-Twin-Account`) or MCP OAuth2 |
| Operations | all 14, including writes like Forget and Correct | the MCP tools: the reads, plus `memory_add` for a key or sign-in that writes |
| Best for | workflows serving many people | one person's agent |

Tested: n8n's MCP Client with Multiple Headers Auth reaches `/v1/mcp` and `memory_grep` finds that end user's
items. Not tested: MCP OAuth2 from n8n.

## 14. Every variable and setting

### In the node itself: none from the environment

The node reads **no environment variables and no files**. n8n's rules for verified nodes forbid both, and its
lint enforces it. Everything comes from:

- **The credential:** `apiKey` and `baseUrl` (section 4).
- **The node's fields:** section 5.

### n8n's own settings that change how it behaves

| Where | Setting | Effect |
| ----- | ------- | ------ |
| Node > Settings | Retry On Fail, Max Tries, Wait Between Tries | retries a failed run; use it for 429 and 503 |
| Node > Settings | Continue On Fail (On Error: Continue) | a failed item becomes `{ error }` instead of stopping the run |
| Node > Settings | Always Output Data | outputs an empty item when there is nothing to output |
| Tool node | Tool Description: Set Automatically / Set Manually, Description | what the model is told (section 10) |
| n8n server | `N8N_COMMUNITY_PACKAGES_ENABLED` | must not be `false`, or community nodes can't be installed |
| n8n server | `N8N_COMMUNITY_PACKAGES_ALLOW_TOOL_USAGE` | not needed in n8n 2.x; older n8n needed it `true` for community nodes as tools |

### On the twin memory API side (the engine's settings, not the node's)

| Setting | Effect on what the node sees |
| ------- | ---------------------------- |
| `MEMORY_KEYS` | customers' keys are on; the account is `<org>.<project>.<End User>`. Unset (a bare local engine), any bearer is accepted, so the credential Test passes with any key |
| `REDIS_URL` | a queue and consumer: Add answers `202` with `pending`, and items land a moment later |
| `OPENROUTER_API_KEY` | the search filter runs (`filtered: true`, one small paid call per search) unless Fast is on |
| `MEMORY_ORG_DAILY_BUDGET_USD` | past the organisation's day budget, Search answers unfiltered, for free |

### In the e2e test (`e2e/run.mjs`, development only)

| Variable | Default | Meaning |
| -------- | ------- | ------- |
| `TWIN_MEMORY_API_KEY` | required | a key that writes, for the API under test |
| `TWIN_MEMORY_BASE_URL` | `http://localhost:8210` | the API as your machine reaches it; n8n in Docker reaches the same port at `host.docker.internal` |
| `N8N_PORT` | `5679` | where the test's n8n listens |

`e2e/docker-compose.yml` runs n8n 2.44.6 with `N8N_DIAGNOSTICS_ENABLED=false`, `N8N_PERSONALIZATION_ENABLED=false`
and `N8N_SECURE_COOKIE=false` (for plain-HTTP localhost). It logs in as `e2e@example.com` /
`E2e-test-password-1`, a local throwaway owner.

### In CI and publishing (`.github/workflows/`)

| Variable | Where | Meaning |
| -------- | ----- | ------- |
| `NPM_TOKEN` | repo secret | an npm token for the first publish; remove it once the trusted publisher is set |
| `GITHUB_REF_NAME` | set by GitHub | the tag; must be `n8n-v<version from package.json>` |
| `GITHUB_ACTIONS` | set by GitHub | makes `n8n-node release` publish (lint, build, `npm publish`) instead of starting the local release-it flow |
| `RELEASE_MODE` | set by `n8n-node release` | lets `npm publish` past the package's `prepublishOnly` guard. Set it yourself (`RELEASE_MODE=true`) only to publish from your laptop |
| `NPM_CONFIG_PROVENANCE` | set by `n8n-node release` in CI | attaches the provenance statement n8n requires |

## 15. Limits

| Limit | Value | Where | What happens |
| ----- | ----- | ----- | ------------ |
| Items per add request | 500 | API | the node splits larger groups itself |
| Request body | 1 MB | API | `413`; 500 long documents can pass it, so send big documents in smaller runs |
| Query, phrase | 2,000 characters | API | `422` |
| End user ID | 64 characters minus the org and project prefix | API | `400` |
| Reads per end user | 10 a second, bursts of 20; 4 requests in hand | API, per process | `429`, with `Retry-After` |
| Results | Latest and Find Phrase at most 50; Width at most 5 | node and API | the field won't go higher |
| Context | Context Length, minimum 200, default 4,000 characters | node | whole entries only |

The node sends one request at a time, so it won't hit the "4 in hand" limit. A fast loop of many reads for the
same end user can hit the per-second limit; Retry On Fail handles that.

## 16. Why it is built this way

- **Programmatic, not declarative.** n8n prefers declarative nodes for plain REST APIs. Two things here need code:
  - Add grouping items across inputs into one request.
  - Search building `context` from the whole answer.
- **No runtime dependencies.** n8n won't verify a node that has any. HTTP goes through n8n's helper, and the
  context builder is written in the package rather than taken from the SDK.
- **The end user is a field, not part of the credential,** so one workflow serves many people and the model can
  never choose it.
- **One node with an Operation field** rather than 14 nodes. That's n8n's convention, and it gives the AI tool
  readable names.
- **No `.d.ts` files in the build.** n8n's verification scanner reads `TwinMemoryApi.credentials.d.ts` as a
  wrongly named credential and fails the package.

## 17. Tests

| Command | What it checks | Needs |
| ------- | -------------- | ----- |
| `npm test` | builds, then 15 unit tests: every operation's route and body, item building, ID checks, the context text, Add batching (1,201 → 500/500/201, two users split, outputs in order), API errors, Continue On Fail, the names saved workflows use, and the credential's default address and documentation links | nothing |
| `npm run lint` | n8n's community-node rules (the same ones verification uses) | nothing |
| `node e2e/run.mjs` | real n8n 2.44.6 in Docker against a memory API (section 14) | Docker, a running API and a key |

The end-to-end test checks:

- n8n loads the node and its tool variant, and the tool has a manual Description.
- The credential Test passes.
- Webhook → Add (wait) → fast Search (the context holds the item) → reply → Forget, and the API then reports the
  item `forgotten`.
- n8n's MCP Client reaches `/v1/mcp` with headers.
- The Telegram template imports, and every node version in it exists.
