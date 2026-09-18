#!/bin/bash
# One online, integrity-checked backup of jobtracker.db (blueprint/wp/WP15-deploy.md §5).
#
# Uses SQLite's backup API through `jobtracker backup` — never `cp` on a WAL database,
# which copies an inconsistent file. Safe while the collector is mid-cycle.
#
# The backup is written into the `jt_backups` volume (the container is non-root and
# cannot write to a host directory), then copied to ${JT_BACKUP_DIR:-./backups} on the
# host — point that at an off-machine mount (NAS, USB, rclone) for real protection.
# 30 rolling days are kept, in the volume and on the host.
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -f docker-compose.prod.yml)
dest="${JT_BACKUP_DIR:-$(grep -E '^JT_BACKUP_DIR=' .env 2>/dev/null | tail -1 | cut -d= -f2)}"
dest="${dest:-./backups}"

if [ -n "$("${compose[@]}" ps --status running --quiet collector)" ]; then
  "${compose[@]}" exec -T collector jobtracker backup --dest /backups
else
  "${compose[@]}" run --rm --no-deps collector jobtracker backup --dest /backups
fi

mkdir -p "$dest"
"${compose[@]}" create --no-recreate collector > /dev/null   # `cp` needs a container to exist
"${compose[@]}" cp collector:/backups/. "$dest"
find "$dest" -maxdepth 1 -name 'jobtracker-*.db' -mtime +30 -delete
echo "backups in $dest: $(find "$dest" -maxdepth 1 -name 'jobtracker-*.db' | wc -l) file(s), newest $(ls -1 "$dest"/jobtracker-*.db | tail -1)"
