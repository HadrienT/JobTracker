#!/bin/bash
# Restore jobtracker.db from a backup file — the procedure in deploy/RUNBOOK.md.
#
#   ./scripts/restore.sh backups/jobtracker-20260918-030000.db
#
# The backup is integrity-checked first, the stack is stopped so nothing is writing,
# the current database is kept aside (never deleted), and the stale -wal/-shm files
# are removed so SQLite cannot replay them onto the restored file.
set -euo pipefail
cd "$(dirname "$0")/.."
backup="${1:?usage: scripts/restore.sh <backup-file>}"
[ -f "$backup" ] || { echo "no such file: $backup" >&2; exit 1; }
compose=(docker compose -f docker-compose.prod.yml)

python3 - "$backup" <<'PY'
import sqlite3, sys
result = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True).execute("PRAGMA integrity_check").fetchone()[0]
sys.exit(0 if result == "ok" else f"refusing to restore: integrity_check says {result!r}")
PY

"${compose[@]}" stop collector api
"${compose[@]}" run --rm --no-deps \
  -v "$(realpath "$backup")":/restore/backup.db:ro \
  --entrypoint sh collector -c '
    set -e
    if [ -f /data/jobtracker.db ]; then
      cp /data/jobtracker.db "/data/jobtracker.db.pre-restore-$(date +%Y%m%d-%H%M%S)"
    fi
    rm -f /data/jobtracker.db-wal /data/jobtracker.db-shm
    cp /restore/backup.db /data/jobtracker.db
    echo "restored $(basename /restore/backup.db) -> /data/jobtracker.db"
  '
"${compose[@]}" up -d
