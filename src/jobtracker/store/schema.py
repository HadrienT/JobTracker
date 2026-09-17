"""Migration location and current schema version.

Applying migrations is `jobtracker.core.db.apply_migrations`'s job (it already
tracks what ran, in `schema_migrations`); this module just points at the
repo's `migrations/` directory and reads that same tracking table back.
"""

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def current_schema_version(conn: sqlite3.Connection) -> str | None:
    """The most recently applied migration's version, or None before any run."""
    try:
        row = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None  # apply_migrations() has never run on this connection
    return str(row["version"]) if row else None
