"""Online, consistent SQLite backups — blueprint/wp/WP15-deploy.md §5.

Never `cp` a WAL database that is in use: the `-wal` file holds committed pages
the main file does not have yet, so a plain copy is silently inconsistent.
SQLite's own backup API (what `sqlite3 .backup` calls) copies a consistent
snapshot while the collector keeps writing, which is why it is used here rather
than needing the `sqlite3` binary inside the image.

A backup nobody has restored is a hypothesis, so each one is integrity-checked
right after it is written and a failing one is deleted, not kept as false comfort.
"""

import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from jobtracker.core.errors import StorageError

DEFAULT_KEEP_DAYS = 30
_NAME = re.compile(r"^jobtracker-(\d{8}-\d{6})\.db$")


def backup_database(
    source: sqlite3.Connection, dest_dir: Path, *, now: datetime, keep_days: int = DEFAULT_KEEP_DAYS
) -> Path:
    """Write `jobtracker-YYYYMMDD-HHMMSS.db` into `dest_dir`, then prune the old ones."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"jobtracker-{now:%Y%m%d-%H%M%S}.db"
    copy = sqlite3.connect(target)
    try:
        source.backup(copy)
        result = _integrity_check(copy)
    finally:
        copy.close()
    if result != "ok":
        target.unlink(missing_ok=True)
        raise StorageError(f"backup failed its integrity check ({result}); removed {target.name}")
    prune_backups(dest_dir, now=now, keep_days=keep_days)
    return target


def _integrity_check(conn: sqlite3.Connection) -> str:
    return str(conn.execute("PRAGMA integrity_check").fetchone()[0])


def prune_backups(dest_dir: Path, *, now: datetime, keep_days: int = DEFAULT_KEEP_DAYS) -> int:
    """Delete backups older than `keep_days` (30 rolling days), judged by their name's timestamp."""
    cutoff = now.replace(tzinfo=None) - timedelta(days=keep_days)
    removed = 0
    for path in dest_dir.glob("jobtracker-*.db"):
        match = _NAME.match(path.name)
        if match and datetime.strptime(match.group(1), "%Y%m%d-%H%M%S") < cutoff:
            path.unlink()
            removed += 1
    return removed
