# Working on n8n-nodes-twinmemory

For whoever changes or releases the node. [README.md](README.md) is for the node's users and ships to npm;
this file and the other notes here do not.

How the node works, in depth: [HOW-IT-WORKS.md](HOW-IT-WORKS.md). Testing and publishing, step by step:
[TESTING-AND-PUBLISHING.md](TESTING-AND-PUBLISHING.md). n8n's scaffold guidance: [AGENTS.md](AGENTS.md).

## Development

```bash
npm ci
npm test                       # build, then unit tests
npm run lint                   # n8n's community node rules
npx prettier --check nodes credentials test e2e
TWIN_MEMORY_API_KEY=tm_... TWIN_MEMORY_BASE_URL=http://localhost:8210 node e2e/run.mjs
```

`e2e/run.mjs` starts n8n 2.44.6 in Docker with this package and runs a real workflow against a memory API.
It checks the credential Test, Add, a fast Search, and Forget; it also checks n8n's MCP Client against
`/v1/mcp` and that the template imports. Its search is fast and its MCP check greps, so the only budget it
spends is on the facts taken from the two items it adds.

`templates/telegram-assistant-memory.json` is the workflow the docs serve at
https://docs.alexein.ai/templates/n8n-telegram-assistant-memory.json (`public/templates/` in
twin-memory-docs). Keep the two the same.

## What ships

`npm pack --dry-run` lists the package. `files` in `package.json` keeps it to the compiled node and
credential, the codex file and the icons, plus the `package.json`, `README.md` and `LICENSE` npm always adds.
Source maps, tests, the e2e set-up, the template, the changelog and these notes stay out.

Everything that ships is public, and so is the template: the README, `package.json`, and every name,
description, placeholder and error message in `nodes/` and `credentials/`. Say what a user sends, gets back and
can rely on, in the words of the docs at https://docs.alexein.ai; never how memory works behind the API, and
never a local stack.

## Releasing

1. Update `version` in `package.json` and `CHANGELOG.md`, and merge.
2. Tag `n8n-v<version>` on main and push it. `.github/workflows/n8n-publish.yml` publishes with provenance.
3. Publishing needs the trusted publisher on npmjs.com (see the workflow's header), or else an `NPM_TOKEN`
   repository secret (an npm granular token that can publish). The package exists since 0.1.0, so the trusted
   publisher can be added now, and no token is needed.
4. Submit the package for verification at [creators.n8n.io](https://creators.n8n.io/nodes).

Provenance needs this repository public (TESTING-AND-PUBLISHING.md, C1). Its history and these notes describe
the engine and the local stack, so making it public is the owner's decision, to make before tagging.
