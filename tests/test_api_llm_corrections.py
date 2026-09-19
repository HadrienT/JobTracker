"""The detail route shows what the LLM changed, and only for the content it read."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.clock import utc_now
from jobtracker.core.models import FieldCorrection
from jobtracker.store import llm_reviews
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting

pytestmark = pytest.mark.db


@pytest.fixture
def seeded(api_conn: sqlite3.Connection) -> None:
    sync_companies(api_conn, [make_board()])
    posting = make_posting(posting_id="p-1", source_job_id="p-1", fingerprint="fp-1")
    upsert_posting(api_conn, posting, make_verdict(posting_id="p-1"))
    api_conn.commit()


def _correct(conn: sqlite3.Connection, *, content_hash: str) -> None:
    llm_reviews.record_corrections(
        conn,
        "p-1",
        [
            FieldCorrection(
                field="compensation",
                before={"amount_min": None},
                after={"amount_min": "120000", "currency": "GBP"},
                evidence="GBP 120k-160k p.a.",
                confidence=0.9,
            )
        ],
        content_hash=content_hash,
        review_version=1,
        now=utc_now(),
    )
    conn.commit()


def test_a_posting_nobody_corrected_has_no_corrections(
    api_client: TestClient, seeded: None
) -> None:
    assert api_client.get("/postings/p-1").json()["llm_corrections"] == []


def test_the_detail_lists_each_correction_with_its_quote(
    api_client: TestClient, api_conn: sqlite3.Connection, seeded: None
) -> None:
    current = api_conn.execute(
        "SELECT content_hash FROM postings WHERE posting_id = 'p-1'"
    ).fetchone()
    _correct(api_conn, content_hash=current["content_hash"])

    (correction,) = api_client.get("/postings/p-1").json()["llm_corrections"]

    assert correction["field"] == "compensation"
    assert correction["before"] == {"amount_min": None}
    assert correction["after"]["amount_min"] == "120000"
    assert correction["evidence"] == "GBP 120k-160k p.a."


def test_a_correction_made_to_older_text_is_not_shown_against_the_new(
    api_client: TestClient, api_conn: sqlite3.Connection, seeded: None
) -> None:
    _correct(api_conn, content_hash="the-hash-of-a-text-that-has-since-changed")

    assert api_client.get("/postings/p-1").json()["llm_corrections"] == []
