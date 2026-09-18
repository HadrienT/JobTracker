"""`runtime.cli` contract tests — blueprint/wp/WP08-runtime.md §6."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from conftest import _API_TEST_ENV
from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.db import apply_migrations, connect
from jobtracker.runtime.cli import main
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting
from jobtracker.store.schema import MIGRATIONS_DIR

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _API_TEST_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("JT_DB_PATH", str(tmp_path / "jobtracker.db"))


def test_migrate_exits_zero() -> None:
    assert main(["migrate"]) == 0


def test_status_on_a_fresh_database_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    main(["migrate"])
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert '"schema_version"' in out


def test_status_exits_one_when_the_feed_is_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "jobtracker.db"
    conn = connect(db_path)
    apply_migrations(conn, MIGRATIONS_DIR)
    sync_companies(conn, [make_board()])
    posting = make_posting(first_seen_at=datetime(2020, 1, 1, tzinfo=UTC))
    upsert_posting(conn, posting, make_verdict())
    conn.commit()
    conn.close()

    assert main(["status"]) == 1
    out = capsys.readouterr().out
    assert '"stale": true' in out
