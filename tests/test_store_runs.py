import sqlite3
from datetime import UTC, datetime

import pytest

from jobtracker.core.enums import Source
from jobtracker.core.models import SourceRun
from jobtracker.store.runs import recent_runs, record_run

pytestmark = pytest.mark.db


def _run(**overrides: object) -> SourceRun:
    base: dict[str, object] = {
        "run_id": "01RUN00000000000000000001",
        "source": Source.GREENHOUSE,
        "company_slug": "acme",
        "started_at": datetime(2026, 1, 1, tzinfo=UTC),
        "ended_at": datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        "fetched": 10,
        "new": 2,
        "updated": 8,
        "aliased": 0,
        "rejected": 1,
        "requests_made": 1,
        "status": "ok",
        "error_kind": None,
    }
    base.update(overrides)
    return SourceRun(**base)  # type: ignore[arg-type]


def test_record_run_persists_the_empty_status_distinctly(store_conn: sqlite3.Connection) -> None:
    record_run(store_conn, _run(status="empty", fetched=0, new=0, updated=0))
    store_conn.commit()

    row = store_conn.execute("SELECT status, fetched FROM source_runs").fetchone()
    assert row["status"] == "empty"
    assert row["fetched"] == 0


def test_recent_runs_orders_newest_first(store_conn: sqlite3.Connection) -> None:
    record_run(store_conn, _run(run_id="r1", started_at=datetime(2026, 1, 1, tzinfo=UTC)))
    record_run(store_conn, _run(run_id="r2", started_at=datetime(2026, 1, 2, tzinfo=UTC)))
    store_conn.commit()

    runs = recent_runs(store_conn, Source.GREENHOUSE, limit=10)
    assert [r.run_id for r in runs] == ["r2", "r1"]


def test_recent_runs_filters_by_source(store_conn: sqlite3.Connection) -> None:
    record_run(store_conn, _run(run_id="r1", source=Source.GREENHOUSE))
    record_run(store_conn, _run(run_id="r2", source=Source.LEVER))
    store_conn.commit()

    runs = recent_runs(store_conn, Source.LEVER, limit=10)
    assert [r.run_id for r in runs] == ["r2"]


def test_an_aggregate_run_has_no_company_slug(store_conn: sqlite3.Connection) -> None:
    record_run(store_conn, _run(run_id="r-agg", company_slug=None))
    store_conn.commit()
    row = store_conn.execute(
        "SELECT company_slug FROM source_runs WHERE run_id = 'r-agg'"
    ).fetchone()
    assert row["company_slug"] is None
