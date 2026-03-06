#!/usr/bin/env bash
set -euo pipefail

python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8080 >/tmp/anpr_api_check.log 2>&1 &
PID=$!
trap 'kill $PID >/dev/null 2>&1 || true' EXIT
sleep 2

echo "[check] GET /"
curl -i -s http://127.0.0.1:8080/ | head -n 8

echo "[check] GET /api/health"
curl -i -s http://127.0.0.1:8080/api/health | head -n 12
