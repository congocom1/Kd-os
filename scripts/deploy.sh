#!/usr/bin/env bash
# scripts/deploy.sh — Build and deploy the full Mark-LVI stack.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

TAG="${1:-latest}"

echo "[deploy] Building Mark-LVI stack (tag: $TAG)..."
docker compose build --parallel

echo "[deploy] Starting stack..."
docker compose up -d

echo "[deploy] Waiting for services to become healthy..."
sleep 10

./scripts/health-check.sh

echo "[deploy] Done. HUD: http://localhost:7860"
