"""SQLite connection, pragmas and migrations — the only place either is set.

A connection opened elsewhere without WAL produces intermittent
``SQLITE_BUSY`` errors, i.e. a bug that does not reproduce
(blueprint/wp/WP01-core.md §2).
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from jobtracker.core.clock import utc_now
from jobtracker.core.errors import StorageError


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with the project's pragmas applied."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on any exception."""
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def apply_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> None:
    """Apply every ``NNNN_description.sql`` file not yet recorded, in order.

    A migration that fails to apply stops the process from starting — see
    blueprint/07-ERRORS-AND-LOGGING.md §3: "on ne sert pas un schéma incertain".
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
    for path in sorted(migrations_dir.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            with transaction(conn):
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, utc_now().isoformat()),
                )
        except sqlite3.Error as exc:
            raise StorageError(f"migration {path.name} failed: {exc}") from exc
