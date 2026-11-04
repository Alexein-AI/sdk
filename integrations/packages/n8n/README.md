# n8n-nodes-twinmemory

An [n8n](https://n8n.io) community node for [Alexein](https://alexein.ai): long-term memory for your users and
AI agents. Add what people say; search it later in plain words. Each end user has a memory of their own.

Documentation: [docs.alexein.ai/integrations/n8n](https://docs.alexein.ai/integrations/n8n).

[Installation](#installation) · [Credential](#credential) · [Operations](#operations) ·
[As an AI Agent tool](#as-an-ai-agent-tool) · [Template](#template) · [MCP instead](#mcp-instead) ·
[Compatibility](#compatibility)

## Installation

In n8n, open **Settings > Community Nodes > Install**, enter `n8n-nodes-twinmemory`, and install. See n8n's
[community node installation guide](https://docs.n8n.io/integrations/community-nodes/installation/).

On n8n Cloud, the node appears once n8n has verified it.

## Credential

Create a **Twin Memory API** credential:

| Field    | Value                                                                                                                      |
| -------- | -------------------------------------------------------------------------------------------------------------------------- |
| API Key  | a key from the Alexein console, under **API keys** (`tm_...`). Use one that writes to add, forget, correct or get versions |
| Base URL | `https://api.alexein.ai`                                                                                                   |

**Test** checks the key against `GET /v1/me`. A credential made with version 0.1.0 can still hold an older
address: set its **Base URL** to `https://api.alexein.ai`.

## Operations

Every operation has an **End User** field: your ID for the person whose memory it is, usually an expression
from the trigger, such as `{{ $json.message.from.id }}`. Each end user's memory is kept apart. See
[End users](https://docs.alexein.ai/concepts/end-users).

| Operation                | What it does                                                              |
| ------------------------ | ------------------------------------------------------------------------- |
| Add                      | Remember a message, note or document                                      |
| Search                   | What memory holds for a question, with a ready-to-paste `context`         |
| Get History              | Every dated value recorded for one subject                                |
| Get Latest               | The newest passages, or every passage between two dates                   |
| Find Phrase              | Every passage holding an exact phrase                                     |
| Read / List              | One passage whole, or what is under a path, by a path another result gave |
| Get Surrounding Passages | The passages either side of one passage                                   |
| Get Overview             | The shape of this end user's memory and its counts                        |
| Get Versions             | An added item's versions, and when and why it went                        |
| Get Status               | How far each added item has got: accepted, landed, read or folded         |
| Get Lineage              | What an item became, or what a fact came from                             |
| Forget                   | Erase items, sessions, threads or events, with a receipt                  |
| Correct                  | Retract one fact, optionally saying what is true instead                  |

**Add** takes the text, a kind (message, note or document), and optional fields: item ID (the same ID again
is an edit of that item), session, role, author, title, about, when, expires and metadata. Input items for
the same end user are sent together, up to 500 per request, and each comes back as its own output item. Turn
on **Wait Until Searchable** to wait up to 10 seconds until they can be found; `pending` counts any not yet
searchable.

**Search** returns `context` (known lines, then worked-out lines, then dated facts, then passages, up to 4,000
characters, which you can change) beside the full answer: `known`, `worked_out`, `facts`, `hits`, `held` and
`filtered`. **Fast** skips the relevance check: free and quicker, a little less precise.

Every other operation returns the API's answer as one item. Errors carry the API's own message. A `429` means
too many requests in flight, or reads too fast; a `503`, that the service is busy or briefly unavailable. For
either, turn on **Retry On Fail** in the node's settings.

### Example: remember a form submission, then answer from memory

1. **Webhook** receives `{ "user": "user_42", "text": "I just moved to Lisbon." }`.
2. **Twin Memory: Add** with End User `{{ $json.body.user }}` and Text `{{ $json.body.text }}`.
3. Later, **Twin Memory: Search** with the same End User and Query `Where does this person live?`. Its
   `context` goes straight into a prompt.

## As an AI Agent tool

The node is usable as a tool: in an **AI Agent**, add a tool and choose **Twin Memory Tool**. Give the agent
two: one with **Search**, one with **Add**.

- **End User:** set it from the trigger, such as `{{ $('Telegram Trigger').item.json.message.from.id }}`, and
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
OpenAI and Twin Memory API credentials.

## MCP instead

n8n's own **MCP Client Tool** can reach Alexein's hosted MCP server, `https://api.alexein.ai/v1/mcp`, with
**HTTP Streamable** transport. Either:

- **Multiple Headers Auth**, with `Authorization: Bearer tm_...` and `X-Twin-Account: <end user>`: one end
  user per credential.
- **MCP OAuth2**: sign in to Alexein and choose the end user.

Use this node when the end user changes per item, and MCP for one person's agent.

## Compatibility

Tested with n8n 2.44.6.

## License

MIT
