# Contributing

For the people who work on this client. It is not part of the npm package.

## Development

```bash
npm install
npm run check                 # types, formatting, tests
npm run build                 # dist/: ESM, CommonJS and types, for each entry point
npm pack --dry-run            # exactly what would go to npm
```

`src/` is split by concern: `calls.ts` describes each request once (path, body, how to read the
answer), `transport.ts` sends it (headers, timeout, retries), `client.ts` and `user.ts` are the
public classes, and `memories.ts`, `search.ts`, `reads.ts`, `pages.ts` and `writes.ts` read the
answers. `langgraph/` and `openai-agents/` are the integrations: built on the client alone, never on
`fetch`, and the only code that imports a framework. `integrations/shared.ts` is what they share.

## Tests

The tests run offline against a `fetch` stub (`test/helpers.ts`): the request each method sends,
the result each answer becomes, retries, every error class, fail-open, paging, batching and
idempotency keys. `test/integrations/` runs both integrations inside the real frameworks, with
scripted models standing in for real ones.

`test/contract.test.ts` holds every method to the API's contract, `../contract/openapi.json`,
which the Python client is held to as well. `../scripts/refresh-openapi.sh` pins it again from a
running service.

`test/live.test.ts` runs the quickstart against a running service, and is skipped unless
`ALEXEIN_API_KEY` is set. It needs a key that writes, and erases the app user it made at the end.

```bash
ALEXEIN_API_KEY=... ALEXEIN_API_URL=http://localhost:8210 npx vitest run test/live.test.ts
```

## What ships

The package is `dist/` (ESM, CommonJS and their types; no source maps), `README.md`,
`CHANGELOG.md`, `LICENSE` and `package.json`: the `files` list in `package.json` says so.

Everything that ships is public, the JSDoc too: it is in `dist/*.d.ts`, and much of it in the built
JavaScript. Write it in the terms of the public docs at docs.alexein.ai: what a caller sends, what
comes back and what is guaranteed, never how the service produces it.

## Releasing

Push a tag `typescript-v<version>` (`typescript-v0.3.0`) that matches `package.json`;
`.github/workflows/typescript-release.yml` checks, builds and publishes with provenance.
