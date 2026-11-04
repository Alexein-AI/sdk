#!/usr/bin/env bash
# Pin the API's developer document for test/contract.test.ts, from a running service.
#   scripts/refresh-openapi.sh [base-url]     default http://localhost:8210
set -euo pipefail
base="${1:-http://localhost:8210}"
curl -fsS "$base/v1/openapi-memory.json" | python3 -m json.tool --indent 1 > test/openapi-memory.json
echo "pinned test/openapi-memory.json from $base"
