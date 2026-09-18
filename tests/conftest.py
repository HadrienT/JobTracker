"""Shared pytest fixtures."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jobtracker.api.app import app
from jobtracker.core.db import apply_migrations, connect
from jobtracker.core.geo import GeoIndex, load_geo_index
from jobtracker.normalize.taxonomy import Taxonomy, load_taxonomy
from jobtracker.store.schema import MIGRATIONS_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent

# blueprint/06-CONFIG.md §1 — every JT_* variable Settings requires with no
# default of its own; the API tests never read a real .env.
_API_TEST_ENV = {
    "JT_LOG_LEVEL": "INFO",
    "JT_LOG_FORMAT": "json",
    "JT_API_HOST": "127.0.0.1",
    "JT_API_PORT": "8100",
    "JT_WEB_PORT": "5190",
    "JT_PUBLIC_API_BASE": "http://127.0.0.1:8100",
    "JT_LLM_ENABLED": "false",
    "JT_LLM_BASE_URL": "http://127.0.0.1:8000/v1",
    "JT_LLM_MODEL": "Qwen3-Coder-30B-A3B-Instruct",
    "JT_LLM_TIMEOUT_S": "60",
    "JT_USER_AGENT": "JobTracker/0.1 (+contact)",
    "JT_HTTP_TIMEOUT_S": "20",
    "JT_AGGREGATORS_ENABLED": "false",
}


@pytest.fixture
def geo_config_path() -> Path:
    return REPO_ROOT / "configs" / "geo.yaml"


@pytest.fixture(scope="session")
def geo_index() -> GeoIndex:
    return load_geo_index(REPO_ROOT / "configs" / "geo.yaml")


@pytest.fixture(scope="session")
def taxonomy() -> Taxonomy:
    return load_taxonomy(REPO_ROOT / "configs" / "taxonomy.yaml")


@pytest.fixture
def store_conn(tmp_path: Path) -> sqlite3.Connection:
    """A fresh SQLite connection with the real migrations/ applied."""
    conn = connect(tmp_path / "jobtracker.db")
    apply_migrations(conn, MIGRATIONS_DIR)
    yield conn
    conn.close()


@pytest.fixture
def api_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A `TestClient` over the real app, migrated against a throwaway database."""
    for key, value in _API_TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("JT_DB_PATH", str(tmp_path / "jobtracker.db"))

    with TestClient(app) as client:
        yield client


@pytest.fixture
def api_conn(api_client: TestClient) -> sqlite3.Connection:
    """The same connection the app's lifespan opened — for seeding test data."""
    conn: sqlite3.Connection = api_client.app.state.conn
    return conn
