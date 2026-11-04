# @alexein/n8n-nodes-alexein

An [n8n](https://n8n.io) community node for [Alexein](https://alexein.ai): long-term memory for your users and
AI agents. Add what people say; search it later in plain words. Each app user has a memory of their own.

Documentation: [docs.alexein.ai/integrations/n8n](https://docs.alexein.ai/integrations/n8n).

[Installation](#installation) · [Credential](#credential) · [Operations](#operations) ·
[As an AI Agent tool](#as-an-ai-agent-tool) · [Template](#template) · [MCP instead](#mcp-instead) ·
[Compatibility](#compatibility)

## Installation

In n8n, open **Settings > Community Nodes > Install**, enter `@alexein/n8n-nodes-alexein`, and install. See n8n's
[community node installation guide](https://docs.n8n.io/integrations/community-nodes/installation/).

On n8n Cloud, the node appears once n8n has verified it.

## Credential

Create an **Alexein API** credential:

| Field    | Value                                                                                                                              |
| -------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| API Key  | a key from the Alexein console, under **API keys** (`tm_...`). Use one that writes to add, forget, correct, get versions or delete |
| Base URL | `https://api.alexein.ai`. The node adds `/v2` itself; a trailing `/` or `/v2` is ignored                                           |

**Test** checks the key against `GET /v2/me`.

## Operations

Every operation but **List App Users** has an **App User** field: your ID for the person whose memory it is,
usually an expression from the trigger, such as `{{ $json.message.from.id }}`. Each app user's memory is kept
apart. See [App users](https://docs.alexein.ai/concepts/app-users).

| Operation                | What it does                                                                  | Route          |
| ------------------------ | ----------------------------------------------------------------------------- | -------------- |
| Add                      | Save a message, note or document                                              | `add`          |
| Search                   | What memory holds for a question, with a ready-to-paste `context`             | `search`       |
| Open                     | One memory whole, by its ref: an excerpt in full, or a fact with its excerpts | `open`         |
| Find Phrase              | Excerpts holding an exact phrase                                              | `grep`         |
| Get Latest               | The most recent excerpts, or every excerpt between two dates                  | `latest`       |
| Get Surrounding Excerpts | The excerpts just before and after one, by its ref                            | `around`       |
| Get History              | Every value a subject was stated to have, and since when                      | `history`      |
| Get Summary              | What this memory holds, in brief                                              | `summary`      |
| List Facts               | The facts memory learned, newest first                                        | `facts`        |
| Get Open Items           | Issues and pull requests still open, and follow-ups nobody answered           | `open_items`   |
| Get Sources              | What each connected app delivered                                             | `sources`      |
| List Items               | The items added, newest first, as they were given                             | `items`        |
| Get Item                 | One added item by its ID                                                      | `item`         |
| Get Status               | How far each added item has got: queued, stored, processed or unknown         | `status`       |
| Get Versions             | An added item's versions, and when and why each went                          | `versions`     |
| Forget                   | Erase items, sessions, or memories by ref, with a receipt                     | `forget`       |
| Correct                  | Retract one fact by its ref, optionally saying what is true instead           | `correct`      |
| Export                   | Everything memory holds for this app user                                     | `export`       |
| List App Users           | Every app user of the key's project with memory, and their counts             | `users`        |
| Delete App User          | Erase this app user's whole memory. Not undone                                | `users/delete` |

Every request is `POST https://api.alexein.ai/v2/memory/<route>`. See the
[API reference](https://docs.alexein.ai/api) for what each takes and answers.

**Add** takes the text, a kind (message, note or document), and optional fields: item ID (the same ID again
is an edit of that item), session, role, author, title, about, when, expires and metadata. Input items for
the same app user are sent together, up to 500 per request, each request with an `Idempotency-Key`, and each
item comes back as its own output item: `{ id, status, waiting }`. Turn on **Wait Until Searchable** to wait,
briefly, until they can be found; **Redact** replaces phone numbers, card numbers, keys and the like before
memory keeps any copy.

**Search** returns `context`, ready to paste into a prompt (the notes, then the memories in order: known lines,
facts and excerpts, up to 4,000 characters, which you can change), beside the full answer: `query`,
`answerable`, `notes` and `memories`. Each fact and excerpt has a `ref` for **Open**, **Get Surrounding
Excerpts**, **Correct** and **Forget**. **Fast** skips the relevance check: free and quicker, a little less
precise. **After**, **Before**, **Filters**, **Provider**, **Source** and **Kind** narrow a search; **Get
Latest** takes the same, and **Find Phrase** takes Provider, Source and Kind.

**List Facts**, **List Items**, **Export** and **List App Users** return one page, with `next` for the
**Cursor** of the page after; turn on **Return All** to get every page as one output item.

Every other operation returns the API's answer as one item. Errors carry the API's own message. A `429` means
too many requests in flight, or reads too fast; a `503`, that the service is busy or briefly unavailable. For
either, turn on **Retry On Fail** in the node's settings: a retried Add sends the same `Idempotency-Key`, so it
never saves an item twice.

### Example: remember a form submission, then answer from memory

1. **Webhook** receives `{ "user": "user_42", "text": "I just moved to Lisbon." }`.
2. **Alexein: Add** with App User `{{ $json.body.user }}` and Text `{{ $json.body.text }}`.
3. Later, **Alexein: Search** with the same App User and Query `Where does this person live?`. Its `context`
   goes straight into a prompt.

## As an AI Agent tool

The node is usable as a tool: in an **AI Agent**, add a tool and choose **Alexein Tool**. Give the agent two:
one with **Search**, one with **Add**. **Open** is a good third, so the agent can read a memory a search
pointed to, by its ref.

- **App User:** set it from the trigger, such as `{{ $('Telegram Trigger').item.json.message.from.id }}`, and
  never leave it to the model, so a model can't reach another person's memory.
- **Query and Text:** let the model fill them with `$fromAI()`, for example
  `{{ $fromAI('query', 'A plain-words question about this person', 'string') }}`.
- **What the model is told:** n8n describes a tool by its operation unless you set **Tool Description** to
  **Set Manually**. For the Add tool, paste this, so the agent saves without being asked:

  > Save to this person's long-term memory (Alexein), which their other apps read too. Call this on your own,
  > without being asked, on every turn where they say anything new: about themselves, their work, or the
  > people, places, projects and things around them - preferences, facts, opinions, decisions, plans, dates,
  > names and numbers, small details and passing remarks. Also save what was asked, tried, decided or built
  > together, and why. When in doubt, save.
  >
  > One fact per call, as a note, in their words. Never save secrets, passwords, keys or payment details, or
  > your own suggestions as facts about them.

## Template

[A Telegram assistant with long-term memory](https://docs.alexein.ai/templates/n8n-telegram-assistant-memory.json):
a Telegram bot that remembers what each person tells it. Simple Memory keeps the last few messages; Alexein keeps
everything else, per Telegram user. Import it with **Workflows > Import from File**, then add your Telegram,
OpenAI and Alexein API credentials.

## MCP instead

n8n's own **MCP Client Tool** can reach Alexein's hosted MCP server, `https://api.alexein.ai/v1/mcp`, with
**HTTP Streamable** transport. Either:

- **Multiple Headers Auth**, with `Authorization: Bearer tm_...` and `X-Alexein-User: <app user>`: one app
  user per credential.
- **MCP OAuth2**: sign in to Alexein. This reaches your own personal memory, never an app user.

Use this node when the app user changes per item, and MCP for one person's agent.

## Compatibility

Tested with n8n 2.44.6.

## License

MIT
