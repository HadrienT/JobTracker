#!/bin/bash
# One online, integrity-checked backup of jobtracker.db (blueprint/wp/WP15-deploy.md §5),
# and an archive of the career folder beside it (CVs and application files, WP22).
#
# Uses SQLite's backup API through `jobtracker backup` — never `cp` on a WAL database,
# which copies an inconsistent file. Safe while the collector is mid-cycle.
#
# The backup is written into the `jt_backups` volume (the container is non-root and
# cannot write to a host directory), then copied to ${JT_BACKUP_DIR:-./backups} on the
# host — point that at an off-machine mount (NAS, USB, rclone) for real protection.
# Databases are compact (`VACUUM INTO`) and gzipped, `jobtracker-*.db.gz`. One copy of each
# is kept (JT_BACKUP_KEEP): the previous one is deleted once the new one is checked. The host
# folder mirrors the volume: what the volume pruned is pruned on the host too.
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
kept="$("${compose[@]}" run --rm --no-deps --entrypoint ls collector -1 /backups)"
for file in "$dest"/jobtracker-*.db "$dest"/jobtracker-*.db.gz "$dest"/career-*.tar.gz; do
  [ -e "$file" ] || continue
  grep -qxF "$(basename "$file")" <<< "$kept" || rm -f "$file"
done
echo "backups in $dest: $(find "$dest" -maxdepth 1 -name 'jobtracker-*.db*' | wc -l) file(s), newest $(ls -1 "$dest"/jobtracker-*.db* | tail -1)"
