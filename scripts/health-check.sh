#!/usr/bin/env bash
# scripts/health-check.sh — Verify all Mark-LVI services are reachable.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

JARVIS_URL="${JARVIS_URL:-http://localhost:7860}"
GEV_URL="${GEV_URL:-http://localhost:4174}"
KRONOS_URL="${KRONOS_URL:-http://localhost:7861}"

check() {
    local name="$1" url="$2"
    if curl -fsS --max-time 5 "$url" >/dev/null 2>&1; then
        echo "✅ $name is healthy ($url)"
    else
        echo "❌ $name is NOT reachable ($url)"
        return 1
    fi
}

echo "[health-check] Checking Mark-LVI services..."
check "JARVIS HUD" "$JARVIS_URL"
check "God's Eye View" "$GEV_URL"
check "Kronos" "$KRONOS_URL/health"
echo "[health-check] All services reachable."
