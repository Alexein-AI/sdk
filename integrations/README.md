# Integrations

Memory from Alexein in other tools, one package per folder. The framework modules themselves
(`alexein.langgraph`, `@alexein/sdk/langgraph`, ...) live in the clients, in [`../python`](../python) and
[`../typescript`](../typescript); what is here sits on top of them.

| Folder | Package | What it is |
| --- | --- | --- |
| [`cli-python`](cli-python) | `alexein-cli` | `uvx alexein-cli init langgraph \| crewai \| openai-agents`: wires memory into a project you have; `create` starts one; `doctor` checks it |
| [`cli-js`](cli-js) | `@alexein/cli` | `npx @alexein/cli init langgraph \| openai-agents`, `create`, `doctor` |
| [`livekit`](livekit) | `alexein-livekit` | Memory for LiveKit voice agents |
| [`n8n`](n8n) | `@alexein/n8n-nodes-alexein` | An n8n community node and AI tool |
