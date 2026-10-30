#!/bin/bash
# Restore jobtracker.db from a backup file — the procedure in deploy/RUNBOOK.md.
#
#   ./scripts/restore.sh backups/jobtracker-20260918-030000.db
#   ./scripts/restore.sh backups/jobtracker-….db backups/career-….tar.gz   # the files too
#
# The backup is integrity-checked first, the stack is stopped so nothing is writing,
# the current database is kept aside (never deleted), and the stale -wal/-shm files
# are removed so SQLite cannot replay them onto the restored file.
set -euo pipefail
cd "$(dirname "$0")/.."
backup="${1:?usage: scripts/restore.sh <backup-file> [career-archive]}"
[ -f "$backup" ] || { echo "no such file: $backup" >&2; exit 1; }
career="${2:-}"
career_mount=()
if [ -n "$career" ]; then
  tar -tzf "$career" > /dev/null || { echo "refusing to restore: unreadable $career" >&2; exit 1; }
  career_mount=(-v "$(realpath "$career")":/restore/career.tar.gz:ro)
fi
compose=(docker compose -f docker-compose.prod.yml)

python3 - "$backup" <<'PY'
import sqlite3, sys
result = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True).execute("PRAGMA integrity_check").fetchone()[0]
sys.exit(0 if result == "ok" else f"refusing to restore: integrity_check says {result!r}")
PY

"${compose[@]}" stop collector api
"${compose[@]}" run --rm --no-deps \
  -v "$(realpath "$backup")":/restore/backup.db:ro "${career_mount[@]}" \
  --entrypoint sh collector -c '
    set -e
    if [ -f /data/jobtracker.db ]; then
      cp /data/jobtracker.db "/data/jobtracker.db.pre-restore-$(date +%Y%m%d-%H%M%S)"
    fi
    rm -f /data/jobtracker.db-wal /data/jobtracker.db-shm
    cp /restore/backup.db /data/jobtracker.db
    echo "restored $(basename /restore/backup.db) -> /data/jobtracker.db"
    if [ -f /restore/career.tar.gz ]; then
      if [ -d /data/career ]; then
        mv /data/career "/data/career.pre-restore-$(date +%Y%m%d-%H%M%S)"
      fi
      tar -xzf /restore/career.tar.gz -C /data
      echo "restored the career folder -> /data/career"
    fi
  '
"${compose[@]}" up -d
