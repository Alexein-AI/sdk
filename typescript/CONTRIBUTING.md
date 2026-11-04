# Contributing

For the people who work on this client. It is not part of the npm package.

## Development

```bash
npm install
npm run check                 # types, formatting, tests
npm run build                 # dist/: ESM, CommonJS and types
npm pack --dry-run            # exactly what would go to npm
```

## End to end

`test/live.test.ts` runs against a running service, and is skipped unless `TWIN_MEMORY_LIVE=1`. It
needs a key that writes, and erases what it added at the end.

```bash
TWIN_MEMORY_LIVE=1 TWIN_MEMORY_API_KEY=tm_... TWIN_MEMORY_BASE_URL=http://localhost:8210 npx vitest run test/live.test.ts
```

## The pinned API document

`test/openapi-memory.json` is the API's own document, pinned; `scripts/refresh-openapi.sh` refreshes
it from a running service (a local stack at `http://localhost:8210` by default), and
`test/contract.test.ts` holds every method to it.

## What ships

The package is `dist/` (ESM, CommonJS and their types; no source maps), `README.md`, `CHANGELOG.md`,
`LICENSE` and `package.json`: the `files` list in `package.json` says so. Tests, scripts, the pinned
document and this file stay here.

Everything that ships is public, the JSDoc too: it is in `dist/*.d.ts`, and much of it in the built
JavaScript. Write it in the terms of the public docs at docs.alexein.ai: what a caller sends, what
comes back and what is guaranteed, never how the service produces it.
