from decimal import Decimal
from pathlib import Path

import pytest

from jobtracker.core.db import apply_migrations, connect
from jobtracker.core.errors import StorageError


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "jobtracker.db"


def test_pragmas_are_set_on_a_fresh_database(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL
    finally:
        conn.close()


def test_decimal_round_trips_through_sqlite_as_text(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.execute("CREATE TABLE amounts (value TEXT NOT NULL)")
        original = Decimal("65000.33")
        conn.execute("INSERT INTO amounts (value) VALUES (?)", (str(original),))
        conn.commit()
        (stored,) = conn.execute("SELECT value FROM amounts").fetchone()
        assert Decimal(stored) == original
        assert isinstance(Decimal(stored), Decimal)
    finally:
        conn.close()


def test_apply_migrations_runs_each_file_once(tmp_path: Path, db_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_create_widgets.sql").write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    (migrations_dir / "0002_seed_widgets.sql").write_text(
        "INSERT INTO widgets (id) VALUES (1);", encoding="utf-8"
    )
    conn = connect(db_path)
    try:
        apply_migrations(conn, migrations_dir)
        assert conn.execute("SELECT COUNT(*) FROM widgets").fetchone()[0] == 1

        # re-applying must not re-run already-recorded migrations
        apply_migrations(conn, migrations_dir)
        assert conn.execute("SELECT COUNT(*) FROM widgets").fetchone()[0] == 1
    finally:
        conn.close()


def test_apply_migrations_raises_storage_error_on_bad_sql(tmp_path: Path, db_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_broken.sql").write_text("NOT VALID SQL;", encoding="utf-8")
    conn = connect(db_path)
    try:
        with pytest.raises(StorageError):
            apply_migrations(conn, migrations_dir)
    finally:
        conn.close()
