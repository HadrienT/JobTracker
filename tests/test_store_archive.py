import sqlite3
from datetime import UTC, datetime

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.store.archive import archive_payload, has_payload, read_payload
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _seed(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    posting = make_posting()
    upsert_posting(store_conn, posting, make_verdict())
    store_conn.commit()


def test_archived_payload_round_trips_through_compression(store_conn: sqlite3.Connection) -> None:
    original = b'{"title": "Quant Developer", "unicode": "d\xc3\xa9veloppeur"}' * 20
    archive_payload(
        store_conn, "01J0000000000000000000P1", original, datetime(2026, 1, 1, tzinfo=UTC)
    )
    store_conn.commit()

    assert read_payload(store_conn, "01J0000000000000000000P1") == original


def test_i7_every_canonical_posting_has_its_archived_payload(
    store_conn: sqlite3.Connection,
) -> None:
    assert not has_payload(store_conn, "01J0000000000000000000P1")
    archive_payload(
        store_conn, "01J0000000000000000000P1", b"raw", datetime(2026, 1, 1, tzinfo=UTC)
    )
    store_conn.commit()
    assert has_payload(store_conn, "01J0000000000000000000P1")


def test_re_archiving_replaces_the_payload(store_conn: sqlite3.Connection) -> None:
    archive_payload(
        store_conn, "01J0000000000000000000P1", b"first", datetime(2026, 1, 1, tzinfo=UTC)
    )
    archive_payload(
        store_conn, "01J0000000000000000000P1", b"second", datetime(2026, 2, 1, tzinfo=UTC)
    )
    store_conn.commit()
    assert read_payload(store_conn, "01J0000000000000000000P1") == b"second"


def test_missing_payload_reads_as_none(store_conn: sqlite3.Connection) -> None:
    assert read_payload(store_conn, "does-not-exist") is None
