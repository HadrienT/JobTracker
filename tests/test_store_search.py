import sqlite3

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import PostingFilter, SortKey, list_postings, upsert_posting
from jobtracker.store.search import index_description, search_posting_ids

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _company(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    store_conn.commit()


def test_diacritics_folded_search_finds_the_accented_title(store_conn: sqlite3.Connection) -> None:
    posting = make_posting(title="Développeur Backend")
    upsert_posting(store_conn, posting, make_verdict())
    store_conn.commit()

    assert search_posting_ids(store_conn, "developpeur") == {posting.posting_id}


def test_index_description_makes_the_body_text_searchable(store_conn: sqlite3.Connection) -> None:
    posting = make_posting()
    upsert_posting(store_conn, posting, make_verdict())
    store_conn.commit()
    index_description(store_conn, posting.posting_id, "We use kdb+ and low-latency C++.")
    store_conn.commit()

    assert search_posting_ids(store_conn, "kdb") == {posting.posting_id}


def test_query_filter_on_posting_filter_uses_full_text_search(
    store_conn: sqlite3.Connection,
) -> None:
    match = make_posting(
        posting_id="p-match",
        source_job_id="j-match",
        fingerprint="fp-match",
        title="Développeur C++",
    )
    other = make_posting(
        posting_id="p-other", source_job_id="j-other", fingerprint="fp-other", title="Sales Manager"
    )
    upsert_posting(store_conn, match, make_verdict(posting_id="p-match"))
    upsert_posting(store_conn, other, make_verdict(posting_id="p-other"))
    store_conn.commit()

    page = list_postings(
        store_conn, PostingFilter(query="developpeur"), SortKey.SCORE, None, limit=10
    )

    assert [row.posting_id for row in page.items] == ["p-match"]
