"""`store.health` contract tests — blueprint/07-ERRORS-AND-LOGGING.md §4-5."""

import sqlite3
from datetime import UTC, datetime

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.clock import freeze
from jobtracker.core.enums import Source
from jobtracker.core.models import SourceRun
from jobtracker.store.companies import sync_companies
from jobtracker.store.health import health_snapshot
from jobtracker.store.postings import upsert_posting
from jobtracker.store.runs import record_run
from jobtracker.store.schema import MIGRATIONS_DIR

pytestmark = pytest.mark.db

_NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _run(**overrides: object) -> SourceRun:
    base: dict[str, object] = {
        "run_id": "r1",
        "source": Source.GREENHOUSE,
        "company_slug": None,
        "started_at": _NOW,
        "ended_at": _NOW,
        "fetched": 10,
        "new": 1,
        "updated": 9,
        "aliased": 0,
        "rejected": 0,
        "requests_made": 1,
        "status": "ok",
        "error_kind": None,
    }
    base.update(overrides)
    return SourceRun(**base)  # type: ignore[arg-type]


def test_source_with_no_enabled_boards_is_disabled(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board(source=Source.LINKEDIN, enabled=False)])
    store_conn.commit()

    snapshot = health_snapshot(store_conn)

    assert len(snapshot.sources) == 1
    assert snapshot.sources[0].status == "disabled"
    assert snapshot.alerts == ()


def test_enabled_source_with_no_runs_yet_is_unknown(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board(source=Source.GREENHOUSE, enabled=True)])
    store_conn.commit()

    snapshot = health_snapshot(store_conn)

    assert snapshot.sources[0].status == "unknown"


def test_healthy_source_reports_ok_with_no_alert(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board(source=Source.GREENHOUSE, enabled=True)])
    record_run(store_conn, _run(status="ok", fetched=100))
    store_conn.commit()

    snapshot = health_snapshot(store_conn)

    assert snapshot.sources[0].status == "ok"
    assert snapshot.sources[0].last_count == 100
    assert snapshot.sources[0].alert is None
    assert snapshot.alerts == ()


def test_n_consecutive_empty_runs_trigger_source_mute(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board(source=Source.GREENHOUSE, enabled=True)])
    for i in range(3):
        started = datetime(2026, 3, 1 + i, tzinfo=UTC)
        record_run(store_conn, _run(run_id=f"r{i}", status="empty", fetched=0, started_at=started))
    store_conn.commit()

    snapshot = health_snapshot(store_conn, empty_runs_before_alert=3)

    assert snapshot.sources[0].status == "degraded"
    assert snapshot.sources[0].alert == "source_mute"
    assert snapshot.alerts[0].kind == "source_mute"
    assert snapshot.alerts[0].source == "greenhouse"


def test_fewer_than_n_empty_runs_does_not_trigger_source_mute(
    store_conn: sqlite3.Connection,
) -> None:
    sync_companies(store_conn, [make_board(source=Source.GREENHOUSE, enabled=True)])
    record_run(
        store_conn,
        _run(run_id="r0", status="empty", fetched=0, started_at=datetime(2026, 3, 1, tzinfo=UTC)),
    )
    record_run(
        store_conn,
        _run(run_id="r1", status="empty", fetched=0, started_at=datetime(2026, 3, 2, tzinfo=UTC)),
    )
    store_conn.commit()

    snapshot = health_snapshot(store_conn, empty_runs_before_alert=3)

    assert snapshot.sources[0].status == "ok"


def test_a_sharp_volume_drop_triggers_volume_drop(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board(source=Source.GREENHOUSE, enabled=True)])
    # A history around 300, then the latest run collapses to 40 (< 20% of 300).
    for i, count in enumerate([310, 295, 305, 300, 290, 40]):
        started = datetime(2026, 3, 1 + i, tzinfo=UTC)
        record_run(store_conn, _run(run_id=f"r{i}", status="ok", fetched=count, started_at=started))
    store_conn.commit()

    snapshot = health_snapshot(store_conn)

    assert snapshot.sources[0].status == "degraded"
    assert snapshot.sources[0].alert == "volume_drop"


def test_mild_volume_change_is_not_a_drop(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board(source=Source.GREENHOUSE, enabled=True)])
    for i, count in enumerate([300, 295, 305, 280]):
        started = datetime(2026, 3, 1 + i, tzinfo=UTC)
        record_run(store_conn, _run(run_id=f"r{i}", status="ok", fetched=count, started_at=started))
    store_conn.commit()

    snapshot = health_snapshot(store_conn)

    assert snapshot.sources[0].status == "ok"


def test_boards_ok_and_boards_error_count_the_latest_run_per_company(
    store_conn: sqlite3.Connection,
) -> None:
    sync_companies(
        store_conn,
        [
            make_board(company_slug="a", source=Source.GREENHOUSE, enabled=True),
            make_board(company_slug="b", source=Source.GREENHOUSE, enabled=True),
        ],
    )
    record_run(store_conn, _run(run_id="a-1", company_slug="a", status="ok", started_at=_NOW))
    record_run(store_conn, _run(run_id="b-1", company_slug="b", status="error", started_at=_NOW))
    store_conn.commit()

    snapshot = health_snapshot(store_conn)

    assert snapshot.sources[0].boards_ok == 1
    assert snapshot.sources[0].boards_error == 1


def test_feed_with_no_postings_is_not_stale(store_conn: sqlite3.Connection) -> None:
    snapshot = health_snapshot(store_conn)
    assert snapshot.feed.active_postings == 0
    assert snapshot.feed.newest_posting_age_h is None
    assert snapshot.feed.stale is False


def test_a_feed_with_no_recent_postings_is_stale(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    posting = make_posting(first_seen_at=datetime(2026, 1, 1, tzinfo=UTC))
    upsert_posting(store_conn, posting, make_verdict())
    store_conn.commit()

    with freeze(_NOW):  # ~59 days after the posting's first_seen_at
        snapshot = health_snapshot(store_conn, global_stale_hours=48)

    assert snapshot.feed.stale is True
    assert any(a.kind == "feed_stale" for a in snapshot.alerts)


def test_a_fresh_feed_is_not_stale(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    posting = make_posting(first_seen_at=_NOW)
    upsert_posting(store_conn, posting, make_verdict())
    store_conn.commit()

    with freeze(_NOW):
        snapshot = health_snapshot(store_conn, global_stale_hours=48)

    assert snapshot.feed.stale is False
    assert snapshot.feed.active_postings == 1


def test_schema_version_reflects_the_latest_applied_migration(
    store_conn: sqlite3.Connection,
) -> None:
    latest = max(int(p.stem.split("_", 1)[0]) for p in MIGRATIONS_DIR.glob("*.sql"))
    snapshot = health_snapshot(store_conn)
    assert snapshot.schema_version == latest
