# Integrations

Memory from Alexein in other tools. Everything twin-memory-integrations held is in this repository, with its
history. Framework integrations are modules of the clients, so `pip install "alexein[langgraph]"` is all a
project needs; the packages in this folder sit on top of them.

## Agent frameworks

| Framework | Python | TypeScript | Docs |
| --- | --- | --- | --- |
| LangGraph | [`alexein.langgraph`](../python/src/alexein/langgraph.py), `pip install "alexein[langgraph]"` | [`@alexein/sdk/langgraph`](../typescript/src/langgraph/index.ts) | [LangGraph](https://docs.alexein.ai/integrations/langgraph) |
| OpenAI Agents SDK | [`alexein.openai_agents`](../python/src/alexein/openai_agents.py), `pip install "alexein[openai-agents]"` | [`@alexein/sdk/openai-agents`](../typescript/src/openai-agents/index.ts) | [OpenAI Agents SDK](https://docs.alexein.ai/integrations/openai-agents) |
| CrewAI | [`alexein.crewai`](../python/src/alexein/crewai.py), `pip install "alexein[crewai]"` | - | [CrewAI](https://docs.alexein.ai/integrations/crewai) |

Each gives the same three things: recall before the model, the turn saved after it, and the tools
`memory_search`, `memory_open` and `memory_add` for the model to call. Whose memory a run reads is the
developer's code's choice, never the model's.

## Packages in this folder

| Folder | Package | What it is |
| --- | --- | --- |
| [`cli-python`](cli-python) | `alexein-cli` | `uvx alexein-cli init langgraph \| openai-agents \| crewai` wires memory into a project you have; `create` starts one; `doctor` checks it |
| [`cli-js`](cli-js) | `@alexein/cli` | `npx @alexein/cli init langgraph \| openai-agents`, `create`, `doctor` |
| [`livekit`](livekit) | `alexein-livekit` | Memory for LiveKit voice agents: recalled before each reply, every turn saved |
| [`n8n`](n8n) | `@alexein/n8n-nodes-alexein` | An n8n community node, usable as an AI agent's tool |

## Where the old repository's parts went

| twin-memory-integrations | Here |
| --- | --- |
| `packages/python` (`twinmemory-cli`) and its LangGraph, OpenAI Agents and CrewAI templates | `cli-python/`; the templates' logic is now `python/src/alexein/{langgraph,openai_agents,crewai}.py` |
| `packages/js` (`twinmemory-cli`) and its LangGraph.js and OpenAI Agents templates | `cli-js/`; the templates' logic is now `typescript/src/{langgraph,openai-agents}/` |
| `packages/livekit` (`twinmemory-livekit`) | `livekit/` |
| `packages/n8n` (`n8n-nodes-twinmemory`) | `n8n/` |
| `scripts/release-rehearsal` | `../scripts/release-rehearsal` |
| `docs/superpowers` (the CrewAI design and plan) | `../docs/superpowers` |
| `vendor/` (built clients for the CLIs) | gone: the CLIs depend on `../python` and `../typescript` directly |
