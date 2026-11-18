#!/usr/bin/env bash
# Build the MARK LVI Linux bundle: PyInstaller onedir + data folders placed
# next to the executable (the app resolves BASE_DIR beside the exe when frozen).
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

PYTHON="${JARVIS_PYTHON:-.venv/bin/python}"
DIST="installer/dist/mark-lvi"

echo "▶ Running PyInstaller…"
"$PYTHON" -m PyInstaller --noconfirm --clean --distpath installer/dist --workpath installer/build installer/mark-lvi.spec

echo "▶ Copying data folders beside the executable…"
# Code folders scanned at runtime by the loaders (loaded from disk by path).
cp -a actions plugins skills "$DIST/"
mkdir -p "$DIST/providers"
cp -a providers/. "$DIST/providers/"
rm -rf "$DIST/providers/voices"   # piper voices download on demand; 61 MB not bundled

# Core data files only — core's Python modules are bundled in _internal.
mkdir -p "$DIST/core"
find core -maxdepth 1 -type f ! -name '*.py' ! -name '*.pyc' -exec cp -a {} "$DIST/core/" \;

# Config: icons + the example template. NEVER the user's api_keys.json or certs.
mkdir -p "$DIST/config"
cp -a config/jarvis.png config/jarvis.ico config/api_keys.example.json "$DIST/config/" 2>/dev/null || true

# Runtime-writable folders the app expects to exist.
mkdir -p "$DIST/memory" "$DIST/data/cache" "$DIST/data/logs" "$DIST/data/shared" \
         "$DIST/data/images" "$DIST/data/code_proposals"

# HUD / studio media.
cp -a assets "$DIST/"
cp -a arc_reactor_model "$DIST/" 2>/dev/null || true

# Knowledge services + awesome-llm agent skills (code only — per-service venvs
# are created by install.sh, never bundled).
mkdir -p "$DIST/apps"
for a in data-analyst knowledge-rag awesome-llm; do
    if [[ -d "apps/$a" ]]; then
        mkdir -p "$DIST/apps/$a"
        (cd "apps/$a" && tar cf - --exclude=./.venv --exclude=./__pycache__ --exclude=./data .) \
            | (cd "$DIST/apps/$a" && tar xf -)
    fi
done
mkdir -p "$DIST/awesome-llm-apps-main"
cp -a awesome-llm-apps-main/agent_skills "$DIST/awesome-llm-apps-main/" 2>/dev/null || true

# Documentation & license.
cp -a README.md LICENSE "$DIST/"
cp -a installer/uninstall.sh "$DIST/"

# Sanity: no secrets may ever land in the bundle.
if [[ -e "$DIST/config/api_keys.json" || -e "$DIST/.env" ]]; then
    echo "✗ Refusing to ship: secrets found in bundle" >&2
    exit 1
fi

echo "✓ Bundle ready at $DIST"
du -sh "$DIST"
