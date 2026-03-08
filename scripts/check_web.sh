#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

cleanup() {
  docker compose down >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker compose up -d --build

echo "[check] GET /api/health через nginx"
curl -i -s "http://127.0.0.1:${HTTP_PORT:-8080}/api/health" | head -n 12

echo "[check] GET /worker/health через nginx"
curl -i -s "http://127.0.0.1:${HTTP_PORT:-8080}/worker/health" | head -n 12
