# Source this in ONE terminal to use the rehearsal's registries there and nowhere else:
#
#   source scripts/release-rehearsal/env.sh
#
# npx and uvx then fetch twinmemory and twinmemory-cli from this machine, and everything else from
# npmjs.org and pypi.org as usual. Its caches are its own, under .cache/ here, so nothing it downloads
# lingers in your usual ones. Do not put this in a shell profile. Close the terminal to undo it.
here="$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" && pwd)"
export npm_config_registry=http://localhost:4873/
export npm_config_cache="$here/.cache/npm"
export npm_config_update_notifier=false
# uv: our index first, and a package it has (twinmemory, twinmemory-cli) is taken only from there.
export UV_INDEX="rehearsal=http://localhost:8070/simple/"
export UV_CACHE_DIR="$here/.cache/uv"
export UV_TOOL_DIR="$here/.cache/uv-tools"
echo "twin memory release rehearsal: npm -> localhost:4873, uv -> localhost:8070 (this terminal only)"
