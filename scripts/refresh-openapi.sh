#!/usr/bin/env bash
# Pin the API's public contract, which both clients' contract tests read: contract/openapi.json.
#   scripts/refresh-openapi.sh [base-url]     default http://localhost:8210 (alexein-stack's memory API)
# Run it after the API changes, then run both clients' tests.
set -euo pipefail
base="${1:-http://localhost:8210}"
repo="$(cd "$(dirname "$0")/.." && pwd)"
curl -fsS "$base/v2/openapi.json" | python3 -m json.tool --indent 1 > "$repo/contract/openapi.json"
echo "pinned contract/openapi.json from $base"
