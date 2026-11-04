# Changelog

## Unreleased

- The credential's Base URL defaults to `https://api.alexein.ai`. A credential made with 0.1.0 can still hold
  the old address: if its Base URL is anything else, set it to `https://api.alexein.ai`.
- The End User field and its error message say what the docs do: up to 35 characters always fits.
- The node's and credential's descriptions, error messages, links, README and template now follow Alexein's
  documentation at https://docs.alexein.ai/integrations/n8n. The node, the credential and every field keep
  their names, so workflows made with 0.1.0 work unchanged.
- The npm package holds only what n8n loads, with the README and licence.

## 0.1.0 - 2026-10-23

First release.

- Twin Memory node, usable as an AI Agent tool: Add, Search, Get History, Get Latest, Find Phrase,
  Read, List, Get Surrounding Passages, Get Overview, Get Versions, Get Status, Get Lineage, Forget
  and Correct.
- Add sends each end user's items together, up to 500 per request. Search returns a ready-to-paste
  `context` beside the raw answer.
- Twin Memory API credential: an API key and a base URL, tested against `GET /v1/me`.
- Template: a Telegram assistant with long-term memory.
