#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -x .jarvis-runtime/node_modules/node/bin/node ]]; then
    export PATH="$PWD/.jarvis-runtime/node_modules/node/bin:$PATH"
fi
node -e 'const [major,minor]=process.versions.node.split(".").map(Number); if (!((major===24 && minor>=14)||major===26)) { console.error("Node 24.14+ or 26 is required"); process.exit(1); }'
if ! vite_bin=$(node -p 'require("node:path").join(require("node:path").dirname(require.resolve("vite/package.json")), "bin", "vite.js")' 2>/dev/null) || [[ ! -f "$vite_bin" ]]; then
    echo "Dependencies missing: run npm ci using a supported Node runtime." >&2
    exit 1
fi
# Keep public data tools and provider configuration on this machine only.
exec node "$vite_bin" --host 127.0.0.1 --port 4174 --strictPort