# Alexein SDK

Long-term memory for your app's users and agents, from [Alexein](https://alexein.ai): the Python and
TypeScript clients, and memory for LangGraph, the OpenAI Agents SDK, CrewAI, LiveKit and n8n.

```bash
pip install alexein          # Python 3.10+
npm install @alexein/sdk     # Node 20+, Bun, Deno, edge runtimes
```

```python
from alexein import Memory

memory = Memory()                      # reads ALEXEIN_API_KEY
dana = memory.user("dana")             # your own id for one of your app users
dana.add("I moved to Lisbon for the job at Acme.", role="user", session="onboarding")
print(dana.search("Where does Dana live?").context())
```

```ts
import { Memory } from "@alexein/sdk";

const dana = new Memory().user("dana");
await dana.add("I moved to Lisbon for the job at Acme.", { role: "user", session: "onboarding" });
console.log((await dana.search("Where does Dana live?")).context());
```

Make a key in the console, under **API keys**. Docs: [docs.alexein.ai](https://docs.alexein.ai).

## Memory for agent frameworks

```python
from alexein.langgraph import AlexeinMemory, MemoryState, MemoryContext   # pip install "alexein[langgraph]"

memory = AlexeinMemory()
builder = StateGraph(MemoryState, context_schema=MemoryContext)
builder.add_node("recall", memory.recall)      # what memory holds for the latest message
builder.add_node("agent", agent)               # memory.prompt(state) goes in its system prompt
builder.add_node("remember", memory.remember)  # the turn, saved
```

Or let the CLI wire it into a project you have: `uvx alexein-cli init langgraph`, `npx @alexein/cli init langgraph`.

## Packages

| Folder | Package | What it is |
| --- | --- | --- |
| [`python`](python) | [`alexein`](https://pypi.org/project/alexein/) | The Python client, sync and async; `alexein.langgraph`, `alexein.openai_agents`, `alexein.crewai` |
| [`typescript`](typescript) | [`@alexein/sdk`](https://www.npmjs.com/package/@alexein/sdk) | The TypeScript client; `@alexein/sdk/langgraph`, `@alexein/sdk/openai-agents` |
| [`integrations/cli-python`](integrations/cli-python) | `alexein-cli` | `uvx alexein-cli init langgraph \| crewai \| openai-agents`, `create`, `doctor` |
| [`integrations/cli-js`](integrations/cli-js) | `@alexein/cli` | `npx @alexein/cli init langgraph \| openai-agents`, `create`, `doctor` |
| [`integrations/livekit`](integrations/livekit) | `alexein-livekit` | Memory for LiveKit voice agents: recalled before each reply, every turn saved |
| [`integrations/n8n`](integrations/n8n) | `@alexein/n8n-nodes-alexein` | An n8n community node, usable as an AI agent's tool |

## In this repository

- [`docs/DESIGN.md`](docs/DESIGN.md) - the one surface both clients and every integration implement.
- [`contract/openapi.json`](contract/openapi.json) - the API's public contract (`/v2/openapi.json`), which both
  clients' contract tests read. `scripts/refresh-openapi.sh [base-url]` pins it again from a running API.
- Each package has its own README, CHANGELOG, tests and CI workflow (`.github/workflows/<package>-*.yml`), and
  releases on its own tag: `python-v*`, `typescript-v*`, `cli-python-v*`, `cli-js-v*`, `livekit-v*`, `n8n-v*`.

This repository joins what were `twin-memory-python`, `twin-memory-js` and `twin-memory-integrations`, with
their history.

MIT licensed.
