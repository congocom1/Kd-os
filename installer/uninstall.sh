#!/usr/bin/env bash
# MARK LVI — uninstaller. Removes the app and its desktop entry.
# Keeps your config/memory unless you pass --purge.
set -euo pipefail

PREFIX="${MARK_LVI_PREFIX:-$HOME/.local/share/mark-lvi}"
APPS_DIR="$HOME/.local/share/applications"

if [[ "${1:-}" == "--purge" ]]; then
    rm -rf "$PREFIX"
    echo "✓ Removed $PREFIX (including your config and memory)."
else
    # Keep user data: config/api_keys.json, config/certs, memory/.
    find "$PREFIX" -mindepth 1 -maxdepth 1 \
        ! -name config ! -name memory ! -name data -exec rm -rf {} +
    find "$PREFIX/config" -mindepth 1 -maxdepth 1 \
        ! -name api_keys.json ! -name certs ! -name jarvis.png ! -name jarvis.ico \
        -exec rm -rf {} + 2>/dev/null || true
    echo "✓ Removed the app; kept your config and memory in $PREFIX"
    echo "  To remove everything: $0 --purge"
fi

rm -f "$APPS_DIR/mark-lvi.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" || true
echo "✓ Removed desktop entry."
