#!/usr/bin/env bash
# Build the four packages from their checkouts and publish them to the rehearsal's registries - and
# only there: every publish names its registry, and no real credentials are used or needed.
#
#   scripts/release-rehearsal/publish.sh
#
# The checkouts are found beside this repository's (../twin-memory-python, ../twin-memory-js), as they
# are for development; set TWIN_MEMORY_PYTHON or TWIN_MEMORY_JS to point elsewhere. Publishing again
# replaces what is there (both registries overwrite a version), so a rerun takes the checkouts' state.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
py_sdk="${TWIN_MEMORY_PYTHON:-$repo/../twin-memory-python}"
js_sdk="${TWIN_MEMORY_JS:-$repo/../twin-memory-js}"
npm_registry=http://localhost:4873/
pypi_upload=http://localhost:8070/
work="$here/.cache/publish"
rm -rf "$work" && mkdir -p "$work"

say() { printf '\n== %s\n' "$*"; }

curl -sf "${npm_registry}-/ping" >/dev/null || { echo "the registries are not up: docker compose up -d in $here"; exit 1; }

# --- npm: a throwaway user on the local registry, and an npmrc that only this script reads --------
token=$(curl -sf -X PUT "${npm_registry}-/user/org.couchdb.user:rehearsal" \
  -H 'content-type: application/json' \
  -d '{"name":"rehearsal","password":"rehearsal-only-local"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
npmrc="$work/npmrc"
printf '//localhost:4873/:_authToken=%s\n' "$token" > "$npmrc"
npm_publish() { npm publish --registry "$npm_registry" --userconfig "$npmrc" --access public "$@"; }
unpublish_if_there() { npm unpublish "$1" --force --registry "$npm_registry" --userconfig "$npmrc" >/dev/null 2>&1 || true; }

say "twinmemory (JavaScript) from $js_sdk"
js_version=$(node -p "require('$js_sdk/package.json').version")
(cd "$js_sdk" && npm ci --silent && npm run build --silent)
unpublish_if_there "twinmemory@$js_version"
(cd "$js_sdk" && npm_publish --ignore-scripts)

say "twinmemory-cli (JavaScript) from packages/langgraph-js"
cli_js="$repo/packages/langgraph-js"
(cd "$cli_js" && npm run build --silent)
# The checkout depends on the client by path, for development; what is published depends on it by
# version, as the release does.
staged="$work/langgraph-js"
mkdir -p "$staged" && cp -R "$cli_js/package.json" "$cli_js/README.md" "$cli_js/CHANGELOG.md" "$cli_js/LICENSE" "$cli_js/dist" "$cli_js/templates" "$staged/"
(cd "$staged" && npm pkg set "dependencies.twinmemory=^$js_version")
cli_js_version=$(node -p "require('$staged/package.json').version")
unpublish_if_there "twinmemory-cli@$cli_js_version"
(cd "$staged" && npm_publish --ignore-scripts)

# --- PyPI: wheels and sdists, uploaded with uv -------------------------------------------------------
py_publish() { uv publish --publish-url "$pypi_upload" --username rehearsal --password rehearsal "$@"; }

say "twinmemory (Python) from $py_sdk"
(cd "$py_sdk" && rm -rf dist && uv build -q && py_publish dist/*)

say "twinmemory-cli (Python) from packages/langgraph-python"
(cd "$repo/packages/langgraph-python" && rm -rf dist && uv build -q && py_publish dist/*)

say "published"
for name in twinmemory twinmemory-cli; do
  printf '  npm   %-16s %s\n' "$name" "$(curl -sf "${npm_registry}$name" | python3 -c 'import sys,json;print(json.load(sys.stdin)["dist-tags"]["latest"])')"
done
curl -sf http://localhost:8070/simple/ | grep -o 'twinmemory[a-z-]*' | sort -u | while read -r name; do
  printf '  pypi  %-16s %s\n' "$name" "$(curl -sf "http://localhost:8070/simple/$name/" | grep -oE "$(echo "$name" | tr - _)-[0-9][^-]*-py3" | sed -E 's/.*-([0-9][^-]*)-py3/\1/' | sort -u | tr '\n' ' ')"
done
