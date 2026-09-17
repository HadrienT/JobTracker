"""Shared pytest fixtures."""

import sqlite3
from pathlib import Path

import pytest

from jobtracker.core.db import apply_migrations, connect
from jobtracker.store.schema import MIGRATIONS_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def geo_config_path() -> Path:
    return REPO_ROOT / "configs" / "geo.yaml"


@pytest.fixture
def store_conn(tmp_path: Path) -> sqlite3.Connection:
    """A fresh SQLite connection with the real migrations/ applied."""
    conn = connect(tmp_path / "jobtracker.db")
    apply_migrations(conn, MIGRATIONS_DIR)
    yield conn
    conn.close()
