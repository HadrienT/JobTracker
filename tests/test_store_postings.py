import sqlite3
from datetime import UTC, datetime

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.enums import RemoteMode, Source, Tier, VisaStatus
from jobtracker.core.errors import StorageError
from jobtracker.core.models import Location, RawPosting, Reason
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import (
    PostingFilter,
    SortKey,
    count_active_canonical,
    get_posting_row,
    get_verdict,
    list_aliases,
    list_postings,
    mark_favorite,
    mark_hidden,
    newest_first_seen_at,
    record_alias,
    upsert_posting,
)

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _company(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    store_conn.commit()


def _upsert(conn: sqlite3.Connection, **overrides: object) -> str:
    posting = make_posting(**overrides)
    posting_id = upsert_posting(conn, posting, make_verdict(posting_id=posting.posting_id))
    conn.commit()
    return posting_id


# --- basic upsert ----------------------------------------------------------


def test_new_fingerprint_creates_a_canonical_posting(store_conn: sqlite3.Connection) -> None:
    posting_id = _upsert(store_conn)
    row = store_conn.execute(
        "SELECT is_canonical, is_active FROM postings WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    assert row["is_canonical"] == 1
    assert row["is_active"] == 1


def test_same_identity_different_content_updates_in_place(store_conn: sqlite3.Connection) -> None:
    posting_id = _upsert(store_conn, content_hash="hash-a", title="Quant Developer")
    posting_id_2 = _upsert(
        store_conn, posting_id=posting_id, content_hash="hash-b", title="Senior Quant Developer"
    )
    assert posting_id_2 == posting_id
    row = store_conn.execute(
        "SELECT title, content_hash FROM postings WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    assert row["title"] == "Senior Quant Developer"
    assert row["content_hash"] == "hash-b"
    assert store_conn.execute("SELECT COUNT(*) c FROM postings").fetchone()["c"] == 1


def test_changed_content_does_not_move_first_seen_at(store_conn: sqlite3.Connection) -> None:
    posting_id = _upsert(
        store_conn, content_hash="hash-a", first_seen_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    _upsert(
        store_conn,
        posting_id=posting_id,
        content_hash="hash-b",
        first_seen_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    row = store_conn.execute(
        "SELECT first_seen_at FROM postings WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    assert row["first_seen_at"] == "2026-01-01T00:00:00+00:00"


def test_unchanged_content_hash_touches_last_seen_but_not_score(
    store_conn: sqlite3.Connection,
) -> None:
    posting_id = _upsert(
        store_conn,
        content_hash="same-hash",
        last_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store_conn.execute(
        "UPDATE verdicts SET scored_at = '2026-01-01T00:00:00+00:00' WHERE posting_id = ?",
        (posting_id,),
    )
    store_conn.commit()

    _upsert(
        store_conn,
        posting_id=posting_id,
        content_hash="same-hash",
        last_seen_at=datetime(2026, 3, 1, tzinfo=UTC),
    )

    posting_row = store_conn.execute(
        "SELECT last_seen_at, score, tier FROM postings WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    verdict_row = store_conn.execute(
        "SELECT scored_at FROM verdicts WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    assert posting_row["last_seen_at"] == "2026-03-01T00:00:00+00:00"
    assert verdict_row["scored_at"] == "2026-01-01T00:00:00+00:00"


def test_favorite_survives_a_full_replay_of_the_same_posting(
    store_conn: sqlite3.Connection,
) -> None:
    posting_id = _upsert(store_conn, content_hash="hash-a")
    mark_favorite(store_conn, posting_id, True)
    store_conn.commit()

    _upsert(store_conn, posting_id=posting_id, content_hash="hash-b", title="Updated title")

    flag = store_conn.execute(
        "SELECT is_favorite FROM user_flags WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    assert flag["is_favorite"] == 1


def test_mark_favorite_and_hidden_are_independent_toggles(store_conn: sqlite3.Connection) -> None:
    posting_id = _upsert(store_conn)
    mark_favorite(store_conn, posting_id, True)
    mark_hidden(store_conn, posting_id, True)
    store_conn.commit()
    row = store_conn.execute(
        "SELECT is_favorite, is_hidden FROM user_flags WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    assert (row["is_favorite"], row["is_hidden"]) == (1, 1)

    mark_favorite(store_conn, posting_id, False)
    store_conn.commit()
    row = store_conn.execute(
        "SELECT is_favorite, is_hidden FROM user_flags WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    assert (row["is_favorite"], row["is_hidden"]) == (0, 1)


# --- dedup resolution — blueprint/wp/WP02-store.md §4 -----------------------


def test_aggregator_arriving_after_an_ats_posting_becomes_an_alias(
    store_conn: sqlite3.Connection,
) -> None:
    ats_id = _upsert(store_conn, posting_id="p-ats", source_job_id="ats-1", fingerprint="fp-shared")
    result_id = _upsert(
        store_conn,
        posting_id="p-agg",
        source=Source.LINKEDIN,
        source_job_id="agg-1",
        fingerprint="fp-shared",
    )

    assert result_id == ats_id
    assert store_conn.execute("SELECT COUNT(*) c FROM postings").fetchone()["c"] == 1
    alias = store_conn.execute(
        "SELECT canonical_id FROM posting_aliases "
        "WHERE source = 'linkedin' AND source_job_id = 'agg-1'"
    ).fetchone()
    assert alias["canonical_id"] == ats_id


def test_ats_arriving_after_an_aggregator_takes_over_as_canonical(
    store_conn: sqlite3.Connection,
) -> None:
    agg_id = _upsert(
        store_conn,
        posting_id="p-agg",
        source=Source.LINKEDIN,
        source_job_id="agg-1",
        fingerprint="fp-shared",
        url="https://linkedin.example/agg-1",
    )
    mark_favorite(store_conn, agg_id, True)
    store_conn.commit()

    ats_id = _upsert(
        store_conn,
        posting_id="p-ats",
        source=Source.GREENHOUSE,
        source_job_id="ats-1",
        fingerprint="fp-shared",
    )

    assert ats_id == "p-ats"
    canonical_rows = store_conn.execute(
        "SELECT posting_id FROM postings WHERE fingerprint = 'fp-shared' AND is_canonical = 1"
    ).fetchall()
    assert [r["posting_id"] for r in canonical_rows] == ["p-ats"]

    demoted = store_conn.execute(
        "SELECT is_canonical FROM postings WHERE posting_id = ?", (agg_id,)
    ).fetchone()
    assert demoted["is_canonical"] == 0

    alias = store_conn.execute(
        "SELECT canonical_id FROM posting_aliases "
        "WHERE source = 'linkedin' AND source_job_id = 'agg-1'"
    ).fetchone()
    assert alias["canonical_id"] == "p-ats"

    old_flag = store_conn.execute(
        "SELECT * FROM user_flags WHERE posting_id = ?", (agg_id,)
    ).fetchone()
    assert old_flag is None
    new_flag = store_conn.execute(
        "SELECT is_favorite FROM user_flags WHERE posting_id = 'p-ats'"
    ).fetchone()
    assert new_flag["is_favorite"] == 1


def test_i4_one_canonical_row_per_fingerprint(store_conn: sqlite3.Connection) -> None:
    _upsert(store_conn, posting_id="p1", source_job_id="j1", fingerprint="fp-x")
    _upsert(
        store_conn,
        posting_id="p2",
        source=Source.LINKEDIN,
        source_job_id="j2",
        fingerprint="fp-x",
    )
    _upsert(store_conn, posting_id="p3", source_job_id="j3", fingerprint="fp-y")

    rows = store_conn.execute(
        "SELECT fingerprint, COUNT(*) c FROM postings WHERE is_canonical = 1 GROUP BY fingerprint"
    ).fetchall()
    counts = {row["fingerprint"]: row["c"] for row in rows}
    assert counts == {"fp-x": 1, "fp-y": 1}


# --- keyset pagination -------------------------------------------------------


def _seed_many(store_conn: sqlite3.Connection, n: int, **overrides: object) -> list[str]:
    ids = []
    for i in range(n):
        pid = f"p{i:04d}"
        _upsert(
            store_conn,
            posting_id=pid,
            source_job_id=f"job-{i}",
            fingerprint=f"fp-{i}",
            **overrides,
        )
        ids.append(pid)
    return ids


@pytest.mark.parametrize("sort", list(SortKey))
def test_keyset_pagination_has_no_overlap_and_no_gap(
    store_conn: sqlite3.Connection, sort: SortKey
) -> None:
    n = 11
    for i in range(n):
        _upsert(
            store_conn,
            posting_id=f"p{i:04d}",
            source_job_id=f"job-{i}",
            fingerprint=f"fp-{i}",
            company_slug="acme",
            closes_at=datetime(2026, 1, 1 + i, tzinfo=UTC) if i % 3 else None,
        )
        store_conn.execute(
            "UPDATE postings SET score = ? WHERE posting_id = ?", (50 + (i % 4), f"p{i:04d}")
        )
    store_conn.commit()

    seen: list[str] = []
    cursor = None
    for _ in range(n + 2):  # generous upper bound on the number of pages
        page = list_postings(store_conn, PostingFilter(), sort, cursor, limit=3)
        seen.extend(row.posting_id for row in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert len(seen) == len(set(seen)), "a posting was served twice"
    assert len(seen) == n, "a posting was skipped"


def test_score_ties_are_broken_by_posting_id_and_stay_stable(
    store_conn: sqlite3.Connection,
) -> None:
    ids = _seed_many(store_conn, 20)
    for pid in ids:
        store_conn.execute("UPDATE postings SET score = 77 WHERE posting_id = ?", (pid,))
    store_conn.commit()

    seen: list[str] = []
    cursor = None
    while True:
        page = list_postings(store_conn, PostingFilter(), SortKey.SCORE, cursor, limit=4)
        seen.extend(row.posting_id for row in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert seen == sorted(ids, reverse=True)


def test_closes_at_sort_puts_postings_without_a_closing_date_last(
    store_conn: sqlite3.Connection,
) -> None:
    _upsert(
        store_conn,
        posting_id="p-none",
        source_job_id="j-none",
        fingerprint="fp-none",
        closes_at=None,
    )
    _upsert(
        store_conn,
        posting_id="p-soon",
        source_job_id="j-soon",
        fingerprint="fp-soon",
        closes_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    _upsert(
        store_conn,
        posting_id="p-later",
        source_job_id="j-later",
        fingerprint="fp-later",
        closes_at=datetime(2026, 6, 1, tzinfo=UTC),
    )

    page = list_postings(store_conn, PostingFilter(), SortKey.CLOSES, None, limit=10)
    order = [row.posting_id for row in page.items]
    assert order == ["p-soon", "p-later", "p-none"]


def test_insertion_during_pagination_does_not_duplicate_already_served_rows(
    store_conn: sqlite3.Connection,
) -> None:
    for i in range(5):
        _upsert(
            store_conn,
            posting_id=f"p{i}",
            source_job_id=f"j{i}",
            fingerprint=f"fp{i}",
        )
        store_conn.execute("UPDATE postings SET score = ? WHERE posting_id = ?", (90 - i, f"p{i}"))
    store_conn.commit()

    page1 = list_postings(store_conn, PostingFilter(), SortKey.SCORE, None, limit=2)
    assert [r.posting_id for r in page1.items] == ["p0", "p1"]

    # A new posting sorting after the served page (lower score) arrives mid-scroll.
    _upsert(store_conn, posting_id="p-new", source_job_id="j-new", fingerprint="fp-new")
    store_conn.execute("UPDATE postings SET score = 10 WHERE posting_id = 'p-new'")
    store_conn.commit()

    page2 = list_postings(store_conn, PostingFilter(), SortKey.SCORE, page1.next_cursor, limit=10)
    ids_page2 = [r.posting_id for r in page2.items]
    assert "p0" not in ids_page2 and "p1" not in ids_page2
    assert ids_page2 == ["p2", "p3", "p4", "p-new"]


def test_invalid_cursor_raises_storage_error(store_conn: sqlite3.Connection) -> None:
    with pytest.raises(StorageError):
        list_postings(store_conn, PostingFilter(), SortKey.SCORE, "not-a-real-cursor", limit=10)


# --- filtering ---------------------------------------------------------------


def test_filter_by_country_uses_posting_locations(store_conn: sqlite3.Connection) -> None:
    _upsert(
        store_conn,
        posting_id="p-fr",
        source_job_id="j-fr",
        fingerprint="fp-fr",
        locations=(
            Location(
                city="Paris", country="FR", region=None, remote_mode=RemoteMode.ONSITE, raw="Paris"
            ),
        ),
    )
    _upsert(
        store_conn,
        posting_id="p-us",
        source_job_id="j-us",
        fingerprint="fp-us",
        locations=(
            Location(
                city="NYC", country="US", region=None, remote_mode=RemoteMode.ONSITE, raw="NYC"
            ),
        ),
    )

    page = list_postings(
        store_conn, PostingFilter(countries=frozenset({"FR"})), SortKey.SCORE, None, limit=10
    )
    assert [r.posting_id for r in page.items] == ["p-fr"]


def test_visa_filter_never_includes_unknown_unless_asked(store_conn: sqlite3.Connection) -> None:
    _upsert(
        store_conn,
        posting_id="p-sponsors",
        source_job_id="j-sponsors",
        fingerprint="fp-sponsors",
        visa_sponsorship=VisaStatus.SPONSORS,
    )
    _upsert(
        store_conn,
        posting_id="p-unknown",
        source_job_id="j-unknown",
        fingerprint="fp-unknown",
        visa_sponsorship=VisaStatus.UNKNOWN,
    )

    page = list_postings(
        store_conn,
        PostingFilter(visa=frozenset({VisaStatus.SPONSORS})),
        SortKey.SCORE,
        None,
        limit=10,
    )
    assert [r.posting_id for r in page.items] == ["p-sponsors"]


def test_hidden_postings_are_excluded_by_default(store_conn: sqlite3.Connection) -> None:
    posting_id = _upsert(store_conn)
    mark_hidden(store_conn, posting_id, True)
    store_conn.commit()

    default_page = list_postings(store_conn, PostingFilter(), SortKey.SCORE, None, limit=10)
    assert default_page.items == ()

    with_hidden = list_postings(
        store_conn, PostingFilter(include_hidden=True), SortKey.SCORE, None, limit=10
    )
    assert [r.posting_id for r in with_hidden.items] == [posting_id]


# --- single-posting readers (WP07) -----------------------------------------


def test_get_posting_row_returns_the_matching_row(store_conn: sqlite3.Connection) -> None:
    posting_id = _upsert(store_conn)
    row = get_posting_row(store_conn, posting_id)
    assert row is not None
    assert row.posting_id == posting_id


def test_get_posting_row_returns_none_for_an_unknown_id(store_conn: sqlite3.Connection) -> None:
    assert get_posting_row(store_conn, "does-not-exist") is None


def test_get_verdict_round_trips_reasons(store_conn: sqlite3.Connection) -> None:
    posting = make_posting()
    verdict = make_verdict(
        posting_id=posting.posting_id,
        tier=Tier.POSSIBLE,
        reasons=(Reason(code="title_strong", delta=35, evidence="Quant Developer"),),
    )
    upsert_posting(store_conn, posting, verdict)
    store_conn.commit()

    fetched = get_verdict(store_conn, posting.posting_id)
    assert fetched is not None
    assert fetched.tier == Tier.POSSIBLE
    assert len(fetched.reasons) == 1
    assert fetched.reasons[0].code == "title_strong"
    assert fetched.reasons[0].delta == 35


def test_get_verdict_returns_none_for_an_unknown_id(store_conn: sqlite3.Connection) -> None:
    assert get_verdict(store_conn, "does-not-exist") is None


def test_list_aliases_returns_republications_newest_first(store_conn: sqlite3.Connection) -> None:
    posting_id = _upsert(store_conn)
    record_alias(
        store_conn,
        posting_id,
        RawPosting(
            source=Source.LINKEDIN,
            company_slug="acme",
            source_job_id="li-1",
            url="https://linkedin.example/li-1",
            title_raw="Quant Developer",
            description_raw="",
            location_raw=None,
            department_raw=None,
            posted_at_raw=None,
            payload=b"",
            fetched_at=datetime(2026, 2, 1, tzinfo=UTC),
            content_hash="hash-alias",
        ),
    )
    store_conn.commit()

    aliases = list_aliases(store_conn, posting_id)
    assert len(aliases) == 1
    assert aliases[0].source == Source.LINKEDIN
    assert aliases[0].source_job_id == "li-1"


def test_count_active_canonical_counts_only_active_canonical_postings(
    store_conn: sqlite3.Connection,
) -> None:
    assert count_active_canonical(store_conn) == 0
    _upsert(store_conn)
    assert count_active_canonical(store_conn) == 1


def test_newest_first_seen_at_is_none_with_no_postings(store_conn: sqlite3.Connection) -> None:
    assert newest_first_seen_at(store_conn) is None


def test_newest_first_seen_at_reflects_the_most_recent_posting(
    store_conn: sqlite3.Connection,
) -> None:
    _upsert(store_conn, first_seen_at=datetime(2026, 1, 1, tzinfo=UTC))
    _upsert(
        store_conn,
        posting_id="p-2",
        source_job_id="j-2",
        fingerprint="fp-2",
        first_seen_at=datetime(2026, 3, 1, tzinfo=UTC),
    )
    newest = newest_first_seen_at(store_conn)
    assert newest is not None
    assert newest.startswith("2026-03-01")
