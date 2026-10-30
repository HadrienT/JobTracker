"""Online, consistent SQLite backups — blueprint/wp/WP15-deploy.md §5.

Never `cp` a WAL database that is in use: the `-wal` file holds committed pages
the main file does not have yet, so a plain copy is silently inconsistent.
SQLite's own backup API (what `sqlite3 .backup` calls) copies a consistent
snapshot while the collector keeps writing, which is why it is used here rather
than needing the `sqlite3` binary inside the image.

A backup nobody has restored is a hypothesis, so each one is integrity-checked
right after it is written and a failing one is deleted, not kept as false comfort.

The database points at files it does not hold: CVs and application folders live under
`career/` (blueprint/wp/WP22-cvs.md). They are archived beside it, read back before the
archive counts. They weigh far more and change far less, so fewer archives are kept.
"""

import re
import sqlite3
import tarfile
from datetime import datetime, timedelta
from pathlib import Path

from jobtracker.core.errors import StorageError

DEFAULT_KEEP_DAYS = 30
CAREER_KEEP_DAYS = 7
_NAME = re.compile(r"^jobtracker-(\d{8}-\d{6})\.db$")
_CAREER_NAME = re.compile(r"^career-(\d{8}-\d{6})\.tar\.gz$")


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


def backup_career(
    career_root: Path, dest_dir: Path, *, now: datetime, keep_days: int = CAREER_KEEP_DAYS
) -> Path | None:
    """Write `career-YYYYMMDD-HHMMSS.tar.gz`, private to its owner, then prune the old ones.
    None when there is no `career/` at all. It only takes its name once read back whole."""
    if not career_root.is_dir():
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"career-{now:%Y%m%d-%H%M%S}.tar.gz"
    partial = target.with_name(f"{target.name}.part")
    expected = sum(path.is_file() for path in career_root.rglob("*"))
    try:
        partial.touch(mode=0o600)
        with tarfile.open(partial, "w:gz") as archive:
            archive.add(career_root, arcname="career")
        found = _archived_files(partial)
    except (OSError, tarfile.TarError, EOFError) as exc:
        partial.unlink(missing_ok=True)
        raise StorageError(f"career backup failed: {exc}") from exc
    if found < expected:
        partial.unlink(missing_ok=True)
        raise StorageError(f"career backup holds {found} files of {expected}; removed")
    partial.replace(target)
    _prune(dest_dir, "career-*.tar.gz", _CAREER_NAME, now=now, keep_days=keep_days)
    return target


def _archived_files(path: Path) -> int:
    """Reads the archive to its end, so a corrupt one fails here."""
    with tarfile.open(path, "r:gz") as archive:
        return sum(member.isfile() for member in archive)


def _integrity_check(conn: sqlite3.Connection) -> str:
    return str(conn.execute("PRAGMA integrity_check").fetchone()[0])


def prune_backups(dest_dir: Path, *, now: datetime, keep_days: int = DEFAULT_KEEP_DAYS) -> int:
    """Delete backups older than `keep_days` (30 rolling days), judged by their name's timestamp."""
    return _prune(dest_dir, "jobtracker-*.db", _NAME, now=now, keep_days=keep_days)


def _prune(
    dest_dir: Path, glob: str, name: re.Pattern[str], *, now: datetime, keep_days: int
) -> int:
    cutoff = now.replace(tzinfo=None) - timedelta(days=keep_days)
    removed = 0
    for path in dest_dir.glob(glob):
        match = name.match(path.name)
        if match and datetime.strptime(match.group(1), "%Y%m%d-%H%M%S") < cutoff:
            path.unlink()
            removed += 1
    return removed
