import sqlite3
from pathlib import Path

import pytest

from jobtracker.core.db import apply_migrations, connect
from jobtracker.store.schema import MIGRATIONS_DIR, current_schema_version

pytestmark = pytest.mark.db


def test_migrations_dir_points_at_the_real_migrations_folder() -> None:
    assert MIGRATIONS_DIR.is_dir()
    assert (MIGRATIONS_DIR / "0001_initial.sql").is_file()


def test_current_schema_version_before_any_migration(tmp_path: Path) -> None:
    conn = connect(tmp_path / "fresh.db")
    try:
        assert current_schema_version(conn) is None
    finally:
        conn.close()


def test_current_schema_version_after_migrating(store_conn: sqlite3.Connection) -> None:
    latest = sorted(p.stem for p in MIGRATIONS_DIR.glob("*.sql"))[-1]
    assert current_schema_version(store_conn) == latest


def test_applying_migrations_twice_is_idempotent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "twice.db")
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        apply_migrations(conn, MIGRATIONS_DIR)
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "postings" in tables
    finally:
        conn.close()
