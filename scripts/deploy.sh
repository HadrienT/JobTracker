#!/bin/bash
# Build, (re)start the production stack, and gate on it actually answering.
# Idempotent and boot-safe: the systemd unit runs it too. See deploy/RUNBOOK.md.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "no .env — run: cp .env.example .env  (then edit it)" >&2; exit 1; }

COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"
export COMMIT_SHA

# Read the port without sourcing .env: values such as the User-Agent contain
# parentheses, which the shell would choke on.
web_port="${JT_WEB_PORT:-$(grep -E '^JT_WEB_PORT=' .env | tail -1 | cut -d= -f2)}"
web_port="${web_port:-5190}"

profiles=()
if grep -qE '^CLOUDFLARE_TUNNEL_TOKEN=.+' .env; then
  profiles=(--profile tunnel)
else
  echo "note: CLOUDFLARE_TUNNEL_TOKEN is empty — starting without the tunnel (local only)" >&2
fi

docker compose -f docker-compose.prod.yml "${profiles[@]}" up -d --build

echo "waiting for the stack on 127.0.0.1:${web_port} ..."
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${web_port}/api/health" > /dev/null; then
    echo "up: front + API answering (commit ${COMMIT_SHA})"
    exit 0
  fi
  sleep 2
done
echo "the stack did not become healthy in 120 s — docker compose -f docker-compose.prod.yml logs" >&2
exit 1
