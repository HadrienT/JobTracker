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

# The commit the stack ran before this deploy: its images are kept to go back to it.
previous="$(docker compose -f docker-compose.prod.yml ps -a --format '{{.Image}}' 2>/dev/null \
  | sed -n 's/^jobtracker-backend://p' | head -1)"

# Each deploy tags its images with its commit, and nothing removed them, so old deploys
# piled up (~2.4 GB each). After a healthy deploy, keep this commit's images and the
# previous one's, remove the other commit-tagged ones. `docker rmi` without -f refuses
# any image a container still uses.
remove_old_images() {
  [[ "$COMMIT_SHA" =~ ^[0-9a-f]{7,40}$ ]] || return 0
  local image tag
  for image in jobtracker-backend jobtracker-web; do
    docker image ls "$image" --format '{{.Tag}}' | while read -r tag; do
      [[ "$tag" =~ ^[0-9a-f]{7,40}$ ]] || continue
      [[ "$tag" == "$COMMIT_SHA" || "$tag" == "$previous" ]] && continue
      docker rmi "$image:$tag" > /dev/null 2>&1 && echo "removed old image $image:$tag" || true
    done
  done
}

docker compose -f docker-compose.prod.yml "${profiles[@]}" up -d --build

echo "waiting for the stack on 127.0.0.1:${web_port} ..."
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:${web_port}/api/health" > /dev/null; then
    echo "up: front + API answering (commit ${COMMIT_SHA})"
    remove_old_images
    exit 0
  fi
  sleep 2
done
echo "the stack did not become healthy in 120 s — docker compose -f docker-compose.prod.yml logs" >&2
exit 1
