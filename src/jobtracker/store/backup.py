"""Online, consistent SQLite backups — blueprint/wp/WP15-deploy.md §5.

Never `cp` a WAL database that is in use: the `-wal` file holds committed pages
the main file does not have yet, so a plain copy is silently inconsistent.
SQLite's `VACUUM INTO` writes a consistent snapshot from one read transaction
while the collector keeps writing, and writes it compact: free pages left by
deleted rows and index merges are not copied. No `sqlite3` binary is needed
inside the image.

A backup nobody has restored is a hypothesis, so each one is integrity-checked
right after it is written and a failing one is deleted, not kept as false comfort.
The checked copy is then gzipped (`jobtracker-*.db.gz`) and the archive is read
back to its end before it takes its name.

The database points at files it does not hold: CVs and application folders live under
`career/` (blueprint/wp/WP22-cvs.md). They are archived beside it, read back before the
archive counts. They weigh far more and change far less, so fewer archives are kept.

Retention counts backups instead of measuring age: the newest backup of each of the
last `keep_daily` days that have one, plus the newest of each of the last `keep_weekly`
ISO weeks. A machine that was off for a month still keeps its last copies.
"""

import gzip
import re
import shutil
import sqlite3
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jobtracker.core.errors import StorageError

_NAME = re.compile(r"^jobtracker-(\d{8}-\d{6})\.db(\.gz)?$")
_CAREER_NAME = re.compile(r"^career-(\d{8}-\d{6})\.tar\.gz$")
_CHUNK = 1 << 20


@dataclass(frozen=True)
class Retention:
    """How many backups survive a prune: one per day, then one per ISO week."""

    daily: int
    weekly: int = 0


DATABASE_RETENTION = Retention(daily=7, weekly=4)
CAREER_RETENTION = Retention(daily=7)


def backup_database(
    source: sqlite3.Connection,
    dest_dir: Path,
    *,
    now: datetime,
    retention: Retention = DATABASE_RETENTION,
) -> Path:
    """Write `jobtracker-YYYYMMDD-HHMMSS.db.gz` into `dest_dir`, then prune the old ones."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"jobtracker-{now:%Y%m%d-%H%M%S}.db.gz"
    snapshot = dest_dir / f".{target.stem}.part"
    partial = target.with_name(f"{target.name}.part")
    try:
        snapshot.unlink(missing_ok=True)
        source.execute("VACUUM INTO ?", (str(snapshot),))
        copy = sqlite3.connect(snapshot)
        try:
            result = _integrity_check(copy)
        finally:
            copy.close()
        if result != "ok":
            raise StorageError(f"backup failed its integrity check ({result}); removed")
        partial.touch(mode=0o600)
        with snapshot.open("rb") as raw, gzip.open(partial, "wb", compresslevel=6) as packed:
            shutil.copyfileobj(raw, packed, _CHUNK)
        if _unpacked_size(partial) != snapshot.stat().st_size:
            raise StorageError("compressed backup does not read back to its full size; removed")
    except (OSError, sqlite3.Error, EOFError) as exc:
        partial.unlink(missing_ok=True)
        raise StorageError(f"database backup failed: {exc}") from exc
    except StorageError:
        partial.unlink(missing_ok=True)
        raise
    finally:
        snapshot.unlink(missing_ok=True)
    partial.replace(target)
    prune_backups(dest_dir, retention=retention)
    return target


def backup_career(
    career_root: Path,
    dest_dir: Path,
    *,
    now: datetime,
    retention: Retention = CAREER_RETENTION,
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
    _prune(dest_dir, _CAREER_NAME, retention)
    return target


def _unpacked_size(path: Path) -> int:
    """Reads the gzip stream to its end, so a truncated or corrupt one fails here."""
    size = 0
    with gzip.open(path, "rb") as packed:
        while chunk := packed.read(_CHUNK):
            size += len(chunk)
    return size


def _archived_files(path: Path) -> int:
    """Reads the archive to its end, so a corrupt one fails here."""
    with tarfile.open(path, "r:gz") as archive:
        return sum(member.isfile() for member in archive)


def _integrity_check(conn: sqlite3.Connection) -> str:
    return str(conn.execute("PRAGMA integrity_check").fetchone()[0])


def prune_backups(dest_dir: Path, *, retention: Retention = DATABASE_RETENTION) -> int:
    """Delete the database backups `retention` does not keep, compressed or not."""
    return _prune(dest_dir, _NAME, retention)


def _prune(dest_dir: Path, name: re.Pattern[str], retention: Retention) -> int:
    stamped: list[tuple[datetime, Path]] = []
    for path in dest_dir.iterdir():
        match = name.match(path.name)
        if match:
            stamped.append((datetime.strptime(match.group(1), "%Y%m%d-%H%M%S"), path))
    stamped.sort(reverse=True)
    keep: set[Path] = set()
    days: set[object] = set()
    weeks: set[object] = set()
    for stamp, path in stamped:  # newest first: the first seen of a day or week is its newest
        day, week = stamp.date(), stamp.isocalendar()[:2]
        if day not in days and len(days) < retention.daily:
            keep.add(path)
        if week not in weeks and len(weeks) < retention.weekly:
            keep.add(path)
        days.add(day)
        weeks.add(week)
    removed = 0
    for _stamp, path in stamped:
        if path not in keep:
            path.unlink()
            removed += 1
    return removed
