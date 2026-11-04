# Working on @alexein/n8n-nodes-alexein

For whoever changes or releases the node. [README.md](README.md) is for the node's users and ships to npm;
this file and the other notes here do not.

How the node works, in depth: [HOW-IT-WORKS.md](HOW-IT-WORKS.md). Testing and publishing, step by step:
[TESTING-AND-PUBLISHING.md](TESTING-AND-PUBLISHING.md). n8n's scaffold guidance: [AGENTS.md](AGENTS.md). The
surface every package in this repository shares, and its names: `docs/DESIGN.md` at the repository root; the API's
contract: `contract/openapi.json`.

## Development

```bash
npm ci
npm test                       # build, then unit tests, checked against contract/openapi.json
npm run lint                   # n8n's community node rules
npx prettier --check nodes credentials test e2e
ALEXEIN_API_KEY=tm_... ALEXEIN_API_URL=http://localhost:8210 node e2e/run.mjs
```

`e2e/run.mjs` starts n8n 2.44.6 in Docker with this package and runs a real workflow against an Alexein API.
It checks the credential Test, Add, a fast Search, and Forget; it also checks n8n's MCP Client against
`/v1/mcp` and that the template imports. Its search is fast and its MCP check greps, so the only budget it
spends is on the facts learned from the two items it adds.

The node calls the API's `/v2` routes itself (n8n won't verify a node with runtime dependencies), in the same
terms as `@alexein/sdk`. When `contract/openapi.json` changes, `npm test` checks that every route and field the
node sends is still in it.

`templates/telegram-assistant-memory.json` is the workflow the docs serve at
https://docs.alexein.ai/templates/n8n-telegram-assistant-memory.json (`public/templates/` in the docs
repository). Keep the two the same.

## What ships

`npm pack --dry-run` lists the package. `files` in `package.json` keeps it to the compiled node and
credential, the codex file and the icons, plus the `package.json`, `README.md` and `LICENSE` npm always adds.
Source maps, tests, the e2e set-up, the template, the changelog and these notes stay out.

Everything that ships is public, and so is the template: the README, `package.json`, and every name,
description, placeholder and error message in `nodes/` and `credentials/`. Say what a user sends, gets back and
can rely on, in the words of the docs at https://docs.alexein.ai (memories, facts, excerpts, refs, app users);
never how memory works behind the API, and never a local stack.

## Releasing

1. Update `version` in `package.json` and `CHANGELOG.md`, and merge.
2. Tag `n8n-v<version>` on main and push it. `.github/workflows/n8n-publish.yml` (at the repository root)
   publishes with provenance.
3. Publishing needs the trusted publisher on npmjs.com (see the workflow's header), or else an `NPM_TOKEN`
   repository secret (an npm granular token that can publish to `@alexein`) for the first publish.
4. Submit the package for verification at [creators.n8n.io](https://creators.n8n.io/nodes).

Provenance needs this repository public (TESTING-AND-PUBLISHING.md, C1); making it public is the owner's
decision, to make before tagging.
