#!/bin/bash
# Browser end-to-end suite against the real compose images — blueprint/wp/WP14-quality.md §2.3.
#
#   scripts/e2e.sh                 run the suite
#   scripts/e2e.sh --update        run it and rewrite the visual baselines
#   E2E_KEEP=1 scripts/e2e.sh      leave the stack up afterwards, for debugging
#
# Seeds a frozen demo database (tools/seed_demo_db.py), brings up api + web on their own
# compose project and ports (so it never collides with a running production stack), runs
# Playwright, and tears everything down — volumes included — whatever the outcome.
set -euo pipefail
cd "$(dirname "$0")/.."
root="$(pwd)"

export JT_WEB_PORT="${E2E_WEB_PORT:-5199}"
export JT_API_PORT="${E2E_API_PORT:-8199}"
COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"
export COMMIT_SHA
compose=(docker compose -p jobtracker-e2e -f "$root/docker-compose.prod.yml" -f "$root/docker-compose.e2e.yml")

cleanup() {
  if [ "${E2E_KEEP:-0}" != "1" ]; then
    "${compose[@]}" down --volumes --remove-orphans > /dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

uv run python tools/seed_demo_db.py e2e/demo.db

"${compose[@]}" up -d --build --wait api web

echo "waiting for the stack on 127.0.0.1:${JT_WEB_PORT} ..."
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${JT_WEB_PORT}/api/health" > /dev/null; then break; fi
  sleep 2
done
curl -sf "http://127.0.0.1:${JT_WEB_PORT}/api/health" > /dev/null

cd web
if [ ! -d node_modules ]; then npm ci; fi
E2E_BASE_URL="http://127.0.0.1:${JT_WEB_PORT}" npx playwright test "$@"
