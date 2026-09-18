import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.store.archive import archive_payload, has_payload
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting
from jobtracker.store.retention import (
    purge_inactive_postings,
    purge_raw_payloads,
    purge_source_runs,
)

pytestmark = pytest.mark.db

_NOW = datetime(2027, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _company(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    store_conn.commit()


def test_purge_raw_payloads_never_cascades_to_the_posting(store_conn: sqlite3.Connection) -> None:
    posting = make_posting(first_seen_at=datetime(2020, 1, 1, tzinfo=UTC))
    upsert_posting(store_conn, posting, make_verdict())
    archive_payload(store_conn, posting.posting_id, b"raw", datetime(2020, 1, 1, tzinfo=UTC))
    store_conn.commit()

    deleted = purge_raw_payloads(store_conn, now=_NOW, retention_days=365)
    store_conn.commit()

    assert deleted == 1
    assert not has_payload(store_conn, posting.posting_id)
    still_there = store_conn.execute(
        "SELECT 1 FROM postings WHERE posting_id = ?", (posting.posting_id,)
    ).fetchone()
    assert still_there is not None


def test_purge_raw_payloads_keeps_recent_ones(store_conn: sqlite3.Connection) -> None:
    posting = make_posting()
    upsert_posting(store_conn, posting, make_verdict())
    archive_payload(store_conn, posting.posting_id, b"raw", _NOW)
    store_conn.commit()

    deleted = purge_raw_payloads(store_conn, now=_NOW, retention_days=365)

    assert deleted == 0
    assert has_payload(store_conn, posting.posting_id)


def test_purge_raw_payloads_uses_a_shorter_window_for_not_quant_rejects(
    store_conn: sqlite3.Connection,
) -> None:
    posting = make_posting()
    verdict = make_verdict(tier="rejected", rejection_reason="not_quant")
    upsert_posting(store_conn, posting, verdict)
    fetched_at = datetime(2026, 10, 1, tzinfo=UTC)  # ~90 days before _NOW, past the short window
    archive_payload(store_conn, posting.posting_id, b"raw", fetched_at)
    store_conn.commit()

    deleted = purge_raw_payloads(
        store_conn, now=_NOW, retention_days=365, rejected_not_quant_retention_days=90
    )

    assert deleted == 1
    assert not has_payload(store_conn, posting.posting_id)


def test_purge_inactive_postings_drops_only_old_inactive_ones(
    store_conn: sqlite3.Connection,
) -> None:
    old_inactive = make_posting(
        posting_id="p-old",
        source_job_id="j-old",
        fingerprint="fp-old",
        last_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    upsert_posting(store_conn, old_inactive, make_verdict(posting_id="p-old"))
    store_conn.execute("UPDATE postings SET is_active = 0 WHERE posting_id = 'p-old'")

    recent_inactive = make_posting(
        posting_id="p-recent",
        source_job_id="j-recent",
        fingerprint="fp-recent",
        last_seen_at=datetime(2026, 12, 1, tzinfo=UTC),
    )
    upsert_posting(store_conn, recent_inactive, make_verdict(posting_id="p-recent"))
    store_conn.execute("UPDATE postings SET is_active = 0 WHERE posting_id = 'p-recent'")

    active = make_posting(posting_id="p-active", source_job_id="j-active", fingerprint="fp-active")
    upsert_posting(store_conn, active, make_verdict(posting_id="p-active"))
    store_conn.commit()

    deleted = purge_inactive_postings(store_conn, now=_NOW, retention_days=180)
    store_conn.commit()

    remaining = {
        row["posting_id"]
        for row in store_conn.execute("SELECT posting_id FROM postings").fetchall()
    }
    assert deleted == 1
    assert remaining == {"p-recent", "p-active"}


def test_purge_source_runs_drops_only_old_rows(store_conn: sqlite3.Connection) -> None:
    from jobtracker.core.enums import Source
    from jobtracker.core.models import SourceRun
    from jobtracker.store.runs import record_run

    record_run(
        store_conn,
        SourceRun(
            run_id="old",
            source=Source.GREENHOUSE,
            company_slug=None,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 1, tzinfo=UTC),
            fetched=0,
            new=0,
            updated=0,
            aliased=0,
            rejected=0,
            requests_made=1,
            status="ok",
            error_kind=None,
        ),
    )
    store_conn.commit()

    deleted = purge_source_runs(store_conn, now=_NOW, retention_days=90)

    assert deleted == 1


# --- WP16 §5, §6: the daily batched run ------------------------------------------------

from jobtracker.core.db import connect  # noqa: E402
from jobtracker.store.postings import mark_favorite  # noqa: E402
from jobtracker.store.retention import run_retention  # noqa: E402

_OLD = datetime(2025, 1, 1, tzinfo=UTC)


def _old_inactive(conn: sqlite3.Connection, pid: str) -> None:
    posting = make_posting(posting_id=pid, source_job_id=pid, first_seen_at=_OLD, last_seen_at=_OLD)
    posting = posting.model_copy(update={"fingerprint": f"fp-{pid}"})
    upsert_posting(conn, posting, make_verdict(posting_id=pid))
    archive_payload(conn, pid, b"raw", _OLD)
    conn.execute("UPDATE postings SET is_active = 0 WHERE posting_id = ?", (pid,))


def test_retention_purges_payloads_and_inactive_postings_but_keeps_active_ones(
    store_conn: sqlite3.Connection,
) -> None:
    _old_inactive(store_conn, "gone")
    active = make_posting(posting_id="alive", source_job_id="alive", first_seen_at=_OLD)
    upsert_posting(
        store_conn,
        active.model_copy(update={"fingerprint": "fp-alive"}),
        make_verdict(posting_id="alive"),
    )
    archive_payload(store_conn, "alive", b"raw", _OLD)
    store_conn.commit()

    result = run_retention(store_conn, now=_NOW, batch_size=1)

    assert result.inactive_postings == 1 and result.raw_payloads >= 1
    remaining = {r["posting_id"] for r in store_conn.execute("SELECT posting_id FROM postings")}
    assert remaining == {"alive"}  # the active posting is kept, payload or not
    assert not has_payload(store_conn, "gone")


def test_a_favorite_survives_its_posting_going_inactive_and_old(
    store_conn: sqlite3.Connection,
) -> None:
    _old_inactive(store_conn, "loved")
    mark_favorite(store_conn, "loved", True)
    store_conn.commit()

    run_retention(store_conn, now=_NOW)
    assert purge_inactive_postings(store_conn, now=_NOW) == 0  # the older entry point agrees
    store_conn.commit()

    flag = store_conn.execute(
        "SELECT is_favorite FROM user_flags WHERE posting_id = 'loved'"
    ).fetchone()
    assert flag is not None and flag["is_favorite"] == 1
    assert store_conn.execute("SELECT 1 FROM postings WHERE posting_id = 'loved'").fetchone()


def test_retention_never_holds_the_write_lock_between_batches(
    store_conn: sqlite3.Connection,
) -> None:
    """A concurrent writer (the API's favorite write) must get in between two batches."""
    for i in range(6):
        _old_inactive(store_conn, f"old-{i}")
    store_conn.commit()
    db_path = store_conn.execute("PRAGMA database_list").fetchone()["file"]
    writer = connect(Path(db_path))
    writer.execute("PRAGMA busy_timeout=0")  # fail instantly if the lock is still held
    writes = []

    def concurrent_write() -> None:
        writer.execute(
            "UPDATE companies SET last_count = last_count + 1 WHERE company_slug = 'acme'"
        )
        writer.commit()
        writes.append(1)

    try:
        result = run_retention(store_conn, now=_NOW, batch_size=1, on_batch=concurrent_write)
    finally:
        writer.close()

    assert result.inactive_postings == 6
    assert len(writes) >= 6  # one successful concurrent write per committed batch
