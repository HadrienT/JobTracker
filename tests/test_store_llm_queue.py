"""`store.llm_queue` and the two `store.postings` doors the LLM lane needs — migration 0003."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.enums import RoleFamily, Seniority, Tier
from jobtracker.store import llm_queue
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import get_posting, get_verdict, update_resolution, upsert_posting

pytestmark = pytest.mark.db

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _company(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    store_conn.commit()


def _store(conn: sqlite3.Connection, posting_id: str, **overrides: object) -> None:
    posting = make_posting(posting_id=posting_id, source_job_id=posting_id, **overrides)
    upsert_posting(
        conn,
        posting.model_copy(update={"fingerprint": f"fp-{posting_id}"}),
        make_verdict(posting_id=posting_id),
    )


def test_enqueue_is_idempotent_and_keeps_attempts(store_conn: sqlite3.Connection) -> None:
    _store(store_conn, "p1")
    llm_queue.enqueue(store_conn, "p1", urgent=False, now=_NOW)
    llm_queue.record_skipped_attempt(store_conn, "p1", now=_NOW)
    llm_queue.enqueue(store_conn, "p1", urgent=True, now=_NOW + timedelta(hours=1))

    entry = llm_queue.get_entry(store_conn, "p1")
    assert entry is not None
    assert entry.attempts == 1  # a re-enqueue never resets the count
    assert entry.urgent is True  # ...but can promote to the urgent lane
    assert entry.queued_at == _NOW.isoformat()  # and keeps its place in line
    assert llm_queue.depth(store_conn) == 1


def test_pending_is_urgent_first_then_oldest(store_conn: sqlite3.Connection) -> None:
    for pid in ("old", "new", "hot"):
        _store(store_conn, pid)
    llm_queue.enqueue(store_conn, "old", urgent=False, now=_NOW)
    llm_queue.enqueue(store_conn, "new", urgent=False, now=_NOW + timedelta(hours=2))
    llm_queue.enqueue(store_conn, "hot", urgent=True, now=_NOW + timedelta(hours=3))
    assert [e.posting_id for e in llm_queue.pending(store_conn, 10)] == ["hot", "old", "new"]


def test_removing_the_posting_cascades_to_the_queue(store_conn: sqlite3.Connection) -> None:
    _store(store_conn, "p1")
    llm_queue.enqueue(store_conn, "p1", urgent=False, now=_NOW)
    store_conn.execute("DELETE FROM postings WHERE posting_id = 'p1'")
    assert llm_queue.depth(store_conn) == 0


def test_get_posting_round_trips_what_match_needs(store_conn: sqlite3.Connection) -> None:
    _store(store_conn, "p1", seniority=Seniority.GRADUATE, min_years=1, resolver_stage="rules")
    posting = get_posting(store_conn, "p1")
    assert posting is not None
    assert posting.seniority == Seniority.GRADUATE
    assert posting.min_years == 1
    assert posting.tech == frozenset({"python"})
    assert posting.locations[0].country == "FR"
    assert get_posting(store_conn, "missing") is None


def test_update_resolution_rewrites_fields_even_with_an_unchanged_content_hash(
    store_conn: sqlite3.Connection,
) -> None:
    _store(store_conn, "p1", seniority=Seniority.UNKNOWN, role_family=RoleFamily.OTHER)
    posting = get_posting(store_conn, "p1")
    assert posting is not None

    # upsert_posting would only touch last_seen_at here; update_resolution must not.
    resolved = posting.model_copy(
        update={
            "seniority": Seniority.JUNIOR,
            "role_family": RoleFamily.QUANT_DEV,
            "resolver_stage": "llm",
        }
    )
    update_resolution(
        store_conn, resolved, make_verdict(posting_id="p1", score=80, tier=Tier.STRONG)
    )

    stored = get_posting(store_conn, "p1")
    verdict = get_verdict(store_conn, "p1")
    assert stored is not None and verdict is not None
    assert stored.seniority == Seniority.JUNIOR
    assert stored.resolver_stage == "llm"
    assert (verdict.score, verdict.tier) == (80, Tier.STRONG)
    row = store_conn.execute("SELECT is_canonical, score FROM postings").fetchone()
    assert (row["is_canonical"], row["score"]) == (1, 80)
