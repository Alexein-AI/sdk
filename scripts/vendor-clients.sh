#!/usr/bin/env bash
# Build the twinmemory clients from their checkouts into vendor/, which the CLIs depend on until the
# clients are on PyPI and npm. Run it after a change to either client, and commit what it writes.
#
#   scripts/vendor-clients.sh
#
# The checkouts are found beside this repository's (../twin-memory-python, ../twin-memory-js); set
# TWIN_MEMORY_PYTHON or TWIN_MEMORY_JS to point elsewhere. Once both clients are published, delete
# vendor/ and this script, and depend on them by version.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
py_sdk="${TWIN_MEMORY_PYTHON:-$repo/../twin-memory-python}"
js_sdk="${TWIN_MEMORY_JS:-$repo/../twin-memory-js}"
vendor="$repo/vendor"
rm -f "$vendor"/twinmemory-*.whl "$vendor"/twinmemory-*.tgz

(cd "$py_sdk" && rm -rf dist && uv build -q --wheel && cp dist/twinmemory-*-py3-none-any.whl "$vendor/")
(cd "$js_sdk" && npm ci --silent && npm run build --silent && npm pack --silent --pack-destination "$vendor" >/dev/null)

echo "vendored, from $(git -C "$py_sdk" rev-parse --short HEAD) and $(git -C "$js_sdk" rev-parse --short HEAD):"
ls -1 "$vendor" | grep -v README
