"""`runtime.watchdog.full_health_snapshot` — the fourth alert, `source_stalled`."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from factories_store import make_board
from jobtracker.collect.http import build_sources_config
from jobtracker.core.enums import Source
from jobtracker.core.models import SourceRun
from jobtracker.runtime.watchdog import full_health_snapshot
from jobtracker.store.companies import sync_companies
from jobtracker.store.runs import record_run

pytestmark = pytest.mark.db

_NOW = datetime(2026, 3, 1, tzinfo=UTC)

_SOURCES_DATA = {
    "defaults": {"timeout_s": 20, "max_requests_per_run": 200, "jitter_s": [2, 7]},
    "sources": {"greenhouse": {"interval_min": 180, "enabled": True}},
}


def _run(minutes_ago: int) -> SourceRun:
    started = _NOW - timedelta(minutes=minutes_ago)
    return SourceRun(
        run_id=f"r-{minutes_ago}",
        source=Source.GREENHOUSE,
        company_slug=None,
        started_at=started,
        ended_at=started,
        fetched=10,
        new=1,
        updated=9,
        aliased=0,
        rejected=0,
        requests_made=1,
        status="ok",
        error_kind=None,
    )


def test_a_source_run_recently_is_not_stalled(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board(source=Source.GREENHOUSE, enabled=True)])
    record_run(store_conn, _run(minutes_ago=10))
    store_conn.commit()

    sources_config = build_sources_config(_SOURCES_DATA)
    snapshot = full_health_snapshot(store_conn, sources_config, now=_NOW)

    assert snapshot.sources[0].status == "ok"
    assert not any(a.kind == "source_stalled" for a in snapshot.alerts)


def test_no_run_since_3x_the_interval_is_stalled(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board(source=Source.GREENHOUSE, enabled=True)])
    # interval_min=180 -> stalled past 540 minutes (9h)
    record_run(store_conn, _run(minutes_ago=600))
    store_conn.commit()

    sources_config = build_sources_config(_SOURCES_DATA)
    snapshot = full_health_snapshot(store_conn, sources_config, now=_NOW)

    assert snapshot.sources[0].status == "degraded"
    assert any(a.kind == "source_stalled" for a in snapshot.alerts)


def test_a_source_with_no_configured_interval_is_never_flagged_stalled(
    store_conn: sqlite3.Connection,
) -> None:
    sync_companies(store_conn, [make_board(source=Source.GREENHOUSE, enabled=True)])
    record_run(store_conn, _run(minutes_ago=100000))
    store_conn.commit()

    sources_config = build_sources_config({"defaults": {}, "sources": {}})
    snapshot = full_health_snapshot(store_conn, sources_config, now=_NOW)

    assert not any(a.kind == "source_stalled" for a in snapshot.alerts)


def test_a_source_with_no_runs_yet_is_never_flagged_stalled(
    store_conn: sqlite3.Connection,
) -> None:
    sync_companies(store_conn, [make_board(source=Source.GREENHOUSE, enabled=True)])
    sources_config = build_sources_config(_SOURCES_DATA)
    snapshot = full_health_snapshot(store_conn, sources_config, now=_NOW)

    assert snapshot.sources[0].status == "unknown"
    assert not any(a.kind == "source_stalled" for a in snapshot.alerts)
