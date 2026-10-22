#!/usr/bin/env bash
# Pin the API's developer document for tests/test_contract.py, from a running service.
#   scripts/refresh-openapi.sh [base-url]     default http://localhost:8210
set -euo pipefail
base="${1:-http://localhost:8210}"
curl -fsS "$base/v1/openapi-memory.json" | python3 -m json.tool --indent 1 > tests/openapi-memory.json
echo "pinned tests/openapi-memory.json from $base"
