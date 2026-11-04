# Changelog

## 0.3.1 - 2026-11-04

- Published through npm's trusted publishing from GitHub Actions, with no token: the provenance on npm is
  GitHub's alone. The client is the same as 0.3.0. A patch release is the package's own; any 0.3.x speaks
  the API's 0.3.

## 0.3.0 - 2026-11-04

Renamed from `twinmemory` to `@alexein/sdk`, rebuilt on the API's `/v2` surface, and numbered as
the API is (`0.3.0`), as the Python client is.

- **Renamed.** The package is `@alexein/sdk`; the base error is `AlexeinError`. The key is read from
  `ALEXEIN_API_KEY` and the host from `ALEXEIN_API_URL`; the User-Agent is `alexein-js/0.3.0`.
- **`/v2`.** Every request goes to `/v2` and names its app user with `X-Alexein-User`. A base URL
  given with a trailing `/` or `/v2` means the same host.
- **Refs, not paths.** Memories come back as known lines, facts and excerpts, told apart by
  `type`; facts and excerpts carry a `ref`, which `open`, `around`, `forget` and `correct` take.
  `read`, `ls`, `overview` and `lineage` are gone: `open` and `summary` replace them.
- **New methods:** `open`, `summary`, `facts`, `openItems`, `sources`, `items`, `item`, `export`,
  `delete`, `memory.users()`, and `iterFacts`, `iterItems`, `iterExport`, `iterUsers` as async
  iterables over every page.
- **Results** are camelCase and keep the API's JSON as `.raw`. `SearchResult.context()` writes the
  notes, a blank line, then each memory on a line, the same text as the Python client.
- **Errors:** every 5xx is a `ServiceUnavailableError`; any other 4xx an `InvalidRequestError`;
  each error has `detail` as a string, `errors` (a 422's fields), `requestId` and `outage`. An app
  user id is checked before any request (a `RangeError`).
- **Integrations**, as their own entry points over optional peer dependencies:
  `@alexein/sdk/langgraph` (LangGraph.js: `AlexeinMemory` with `recall`, `remember`, `prompt` and
  `tools`, `MemoryAnnotation`, `MemoryContext`) and `@alexein/sdk/openai-agents` (the OpenAI Agents
  SDK: `recall` as a `callModelInputFilter`, `remember`, `tools`). The main entry imports no
  framework.
- Still no runtime dependencies; ESM and CommonJS with types, Node 20 or newer, edge runtimes.
- Every call sends an `X-Request-Id` of its own (`req_...`), kept across its retries, and every error
  carries it as `requestId` - even a 500 a proxy answered, or no answer at all - so it can be found in
  the console's request logs.

## 0.1.0

First release, over the API's earlier routes, under the old package name.
