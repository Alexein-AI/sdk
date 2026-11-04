# Changelog

## 0.3.1 - 2026-11-04

- Published through npm's trusted publishing from GitHub Actions, with no token, so the npm provenance n8n
  checks before it verifies a community node is GitHub's alone. The node is the same as 0.3.0.

## 0.3.0 - 2026-11-04

The first release on npm, as `@alexein/n8n-nodes-alexein`, on the Alexein API's `/v2` surface. Renamed from
`n8n-nodes-twinmemory` 0.1.0, which was never published; nothing made with it carries over.

- **Names.** The node is **Alexein** (`alexein`; as an AI tool, **Alexein Tool**), the credential **Alexein
  API** (`alexeinApi`). The **End User** field is now **App User** (`user`), and takes what the API takes: 1 to
  35 letters, digits, `.`, `_` and `-`, beginning with a letter or digit.
- **v2.** Every request is `POST {Base URL}/v2/memory/<route>` with `X-Alexein-User` (none on List App Users),
  and the credential's **Test** is `GET /v2/me`. A Base URL with a trailing `/` or `/v2` means the same host.
  Answers are the API's v2 shapes: memories, facts and excerpts, each with a ref.
- **Operations.** Read is now **Open**, by a ref; Get Overview is **Get Summary**; Get Surrounding Passages is
  **Get Surrounding Excerpts**, by a ref. **Correct** takes a fact's ref, **Forget** takes item IDs, sessions
  and refs, and **Get Status** takes item IDs and answers `queued`, `stored`, `processed` or `unknown`. List and
  Get Lineage are gone: Open shows what a fact was learned from.
- **New operations:** List Facts, List Items, Get Item, Get Open Items, Get Sources, Export, List App Users and
  Delete App User. The listing ones return a page, with a Cursor, or every page with **Return All**.
- **Search, Get Latest and Find Phrase** narrow by **Provider**, **Source** and **Kind**; Search and Get Latest
  also by **Filters** (author, mentions, metadata). Search's old Scope, and Find Phrase's, are gone.
- **Search's `context`** is the notes, then each memory on a line (excerpts dated), as the SDKs give it.
- **Add** sends an `Idempotency-Key` with every request, the same when Retry On Fail sends it again, so a retry
  never saves an item twice; and has a **Redact** option. Each item answers `{ id, status, waiting }`.
- **Errors** carry the API's `detail`; on a `422`, the description names each field.
- The npm package holds only what n8n loads, with the README and licence.
