import sqlite3
from datetime import UTC, datetime

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.enums import RemoteMode, Source, Tier, Triage, VisaStatus
from jobtracker.core.errors import StorageError
from jobtracker.core.models import Location, RawPosting, Reason
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import (
    PostingFilter,
    SortKey,
    count_active_canonical,
    deactivate_missing,
    find_duplicates,
    get_posting_row,
    get_verdict,
    list_aliases,
    list_postings,
    mark_favorite,
    mark_hidden,
    merge_duplicates,
    newest_first_seen_at,
    record_alias,
    resolve_dedup,
    resolve_posting_id,
    set_triage,
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


def test_a_reposted_role_takes_over_from_its_closed_listing(
    store_conn: sqlite3.Connection,
) -> None:
    # The board closed requisition j-1 and reopened the same role as j-2: aliasing j-2 to
    # the closed j-1 would keep a live posting out of the feed.
    old_id = _upsert(store_conn, posting_id="p-old", source_job_id="j-1", fingerprint="fp-r")
    set_triage(store_conn, old_id, Triage.NO)
    deactivate_missing(store_conn, Source.GREENHOUSE, "acme", {"j-other"})
    store_conn.commit()

    repost = make_posting(posting_id="p-new", source_job_id="j-2", fingerprint="fp-r")
    assert resolve_dedup(store_conn, repost) is None
    new_id = _upsert(store_conn, posting_id="p-new", source_job_id="j-2", fingerprint="fp-r")

    assert new_id == "p-new"
    rows = {
        r["posting_id"]: (r["is_canonical"], r["is_active"])
        for r in store_conn.execute("SELECT posting_id, is_canonical, is_active FROM postings")
    }
    assert rows == {"p-old": (0, 0), "p-new": (1, 1)}
    alias = store_conn.execute(
        "SELECT canonical_id FROM posting_aliases WHERE source_job_id = 'j-1'"
    ).fetchone()
    assert alias["canonical_id"] == "p-new"
    flag = store_conn.execute("SELECT triage FROM user_flags WHERE posting_id = 'p-new'").fetchone()
    assert flag["triage"] == Triage.NO.value


def test_a_sibling_aliased_while_the_canonical_was_listed_takes_over_once_it_closes(
    store_conn: sqlite3.Connection,
) -> None:
    _upsert(store_conn, posting_id="p-a", source_job_id="j-a", fingerprint="fp-s")
    assert _upsert(store_conn, posting_id="p-b", source_job_id="j-b", fingerprint="fp-s") == "p-a"
    deactivate_missing(store_conn, Source.GREENHOUSE, "acme", {"j-b"})

    assert _upsert(store_conn, posting_id="p-b", source_job_id="j-b", fingerprint="fp-s") == "p-b"

    aliases = {
        r["source_job_id"]: r["canonical_id"]
        for r in store_conn.execute("SELECT source_job_id, canonical_id FROM posting_aliases")
    }
    assert aliases == {"j-a": "p-b"}


def test_a_demoted_posting_listed_again_reclaims_a_closed_canonical(
    store_conn: sqlite3.Connection,
) -> None:
    _upsert(store_conn, posting_id="p-old", source_job_id="j-1", fingerprint="fp-r")
    deactivate_missing(store_conn, Source.GREENHOUSE, "acme", {"j-other"})
    _upsert(store_conn, posting_id="p-new", source_job_id="j-2", fingerprint="fp-r")
    deactivate_missing(store_conn, Source.GREENHOUSE, "acme", {"j-1"})

    _upsert(store_conn, posting_id="p-old", source_job_id="j-1", fingerprint="fp-r")

    canonical = store_conn.execute(
        "SELECT posting_id, is_active FROM postings WHERE is_canonical = 1"
    ).fetchall()
    assert [(r["posting_id"], r["is_active"]) for r in canonical] == [("p-old", 1)]


def test_an_aggregator_never_takes_over_a_closed_ats_posting(
    store_conn: sqlite3.Connection,
) -> None:
    ats_id = _upsert(store_conn, posting_id="p-ats", source_job_id="ats-1", fingerprint="fp-c")
    deactivate_missing(store_conn, Source.GREENHOUSE, "acme", {"j-other"})

    aggregator = make_posting(
        posting_id="p-agg", source=Source.LINKEDIN, source_job_id="agg-1", fingerprint="fp-c"
    )
    assert resolve_dedup(store_conn, aggregator) == ats_id


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


# --- resolve_posting_id / resolve_dedup (WP08) ------------------------------


def test_resolve_posting_id_allocates_a_fresh_id_for_an_unseen_identity(
    store_conn: sqlite3.Connection,
) -> None:
    allocated = resolve_posting_id(store_conn, Source.GREENHOUSE, "acme", "job-999")
    assert isinstance(allocated, str)
    assert allocated != ""


def test_resolve_posting_id_reuses_the_existing_id(store_conn: sqlite3.Connection) -> None:
    posting_id = _upsert(store_conn)
    posting = make_posting()
    reused = resolve_posting_id(
        store_conn, posting.source, posting.company_slug, posting.source_job_id
    )
    assert reused == posting_id


def test_resolve_dedup_is_none_for_a_brand_new_fingerprint(store_conn: sqlite3.Connection) -> None:
    posting = make_posting()
    assert resolve_dedup(store_conn, posting) is None


def test_resolve_dedup_is_none_for_an_existing_identity_update(
    store_conn: sqlite3.Connection,
) -> None:
    _upsert(store_conn)
    updated = make_posting(content_hash="new-hash")  # same identity as _upsert's default
    assert resolve_dedup(store_conn, updated) is None


def test_resolve_dedup_flags_an_aggregator_republication_as_an_alias_of_an_existing_ats_posting(
    store_conn: sqlite3.Connection,
) -> None:
    canonical_id = _upsert(store_conn, source=Source.GREENHOUSE, fingerprint="fp-shared")

    aggregator_posting = make_posting(
        posting_id="p-linkedin",
        source=Source.LINKEDIN,
        source_job_id="j-linkedin",
        fingerprint="fp-shared",
    )
    assert resolve_dedup(store_conn, aggregator_posting) == canonical_id


def test_resolve_dedup_is_none_when_an_ats_posting_takes_over_from_an_aggregator(
    store_conn: sqlite3.Connection,
) -> None:
    _upsert(store_conn, source=Source.LINKEDIN, fingerprint="fp-shared")
    ats_posting = make_posting(
        posting_id="p-ats", source=Source.GREENHOUSE, source_job_id="j-ats", fingerprint="fp-shared"
    )
    assert resolve_dedup(store_conn, ats_posting) is None


# --- deactivate_missing (WP08) ----------------------------------------------


def test_deactivate_missing_turns_off_a_posting_absent_from_the_run(
    store_conn: sqlite3.Connection,
) -> None:
    still_there = _upsert(store_conn, posting_id="p-1", source_job_id="j-1", fingerprint="fp-1")
    gone = _upsert(store_conn, posting_id="p-2", source_job_id="j-2", fingerprint="fp-2")

    changed = deactivate_missing(store_conn, Source.GREENHOUSE, "acme", {"j-1"})
    store_conn.commit()

    assert changed == 1
    rows = {
        r["posting_id"]: r["is_active"]
        for r in store_conn.execute("SELECT posting_id, is_active FROM postings").fetchall()
    }
    assert rows[still_there] == 1
    assert rows[gone] == 0


def test_a_posting_the_board_lists_again_is_active_again(
    store_conn: sqlite3.Connection,
) -> None:
    # A cycle that saw only part of a listing deactivates what it missed; the posting
    # is unchanged when a later cycle sees it, and must not stay hidden for that.
    posting_id = _upsert(store_conn, source_job_id="j-1", content_hash="same-hash")
    deactivate_missing(store_conn, Source.GREENHOUSE, "acme", {"j-other"})

    _upsert(store_conn, posting_id=posting_id, source_job_id="j-1", content_hash="same-hash")
    store_conn.commit()

    row = store_conn.execute(
        "SELECT is_active FROM postings WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    assert row["is_active"] == 1


def test_deactivate_missing_with_an_empty_seen_set_changes_nothing(
    store_conn: sqlite3.Connection,
) -> None:
    _upsert(store_conn)
    changed = deactivate_missing(store_conn, Source.GREENHOUSE, "acme", set())
    assert changed == 0
    row = store_conn.execute("SELECT is_active FROM postings").fetchone()
    assert row["is_active"] == 1


def test_triage_keeps_the_favorite_and_the_application_status(
    store_conn: sqlite3.Connection,
) -> None:
    posting_id = _upsert(store_conn)
    mark_favorite(store_conn, posting_id, True)
    set_triage(store_conn, posting_id, Triage.MAYBE)
    store_conn.commit()

    assert list_postings(store_conn, PostingFilter(), SortKey.SCORE, None, limit=10).items == ()
    page = list_postings(store_conn, PostingFilter(triage=Triage.MAYBE), SortKey.SCORE, None, 10)
    assert [(r.posting_id, r.triage, r.is_favorite) for r in page.items] == [
        (posting_id, Triage.MAYBE, True)
    ]

    set_triage(store_conn, posting_id, None)
    store_conn.commit()
    back = list_postings(store_conn, PostingFilter(), SortKey.SCORE, None, limit=10)
    assert [(r.posting_id, r.triage, r.is_favorite) for r in back.items] == [
        (posting_id, None, True)
    ]


def _canonical(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT posting_id FROM postings WHERE is_canonical = 1").fetchall()
    return {row["posting_id"] for row in rows}


def test_a_live_sibling_requisition_is_kept_apart_not_hidden(
    store_conn: sqlite3.Connection,
) -> None:
    """Same title, same unknown country, another city: a role of its own (issue #8)."""
    _upsert(store_conn, posting_id="p-ldn", source_job_id="j-1", fingerprint="fp", content_hash="a")
    posting = make_posting(
        posting_id="p-mnl", source_job_id="j-2", fingerprint="fp", content_hash="b"
    )
    assert resolve_dedup(store_conn, posting) is None
    assert upsert_posting(store_conn, posting, make_verdict(posting_id="p-mnl")) == "p-mnl"
    assert _canonical(store_conn) == {"p-ldn", "p-mnl"}


def test_the_same_content_under_another_requisition_is_still_a_duplicate(
    store_conn: sqlite3.Connection,
) -> None:
    _upsert(store_conn, posting_id="p-a", source_job_id="j-1", fingerprint="fp", content_hash="a")
    posting = make_posting(
        posting_id="p-b", source_job_id="j-2", fingerprint="fp", content_hash="a"
    )
    assert resolve_dedup(store_conn, posting) == "p-a"


def test_a_sibling_prefers_its_exact_twin_among_several_canonicals(
    store_conn: sqlite3.Connection,
) -> None:
    for name, content in (("a", "ca"), ("b", "cb")):
        _upsert(
            store_conn,
            posting_id=f"p-{name}",
            source_job_id=f"j-{name}",
            fingerprint="fp",
            content_hash=content,
        )
    twin = make_posting(posting_id="p-c", source_job_id="j-c", fingerprint="fp", content_hash="cb")
    assert resolve_dedup(store_conn, twin) == "p-b"


def test_a_posting_seen_as_an_alias_stops_being_one_when_it_becomes_a_sibling(
    store_conn: sqlite3.Connection,
) -> None:
    """What the old rule hid comes back by itself, at the next collection."""
    _upsert(store_conn, posting_id="p-a", source_job_id="j-1", fingerprint="fp", content_hash="a")
    _upsert(store_conn, posting_id="p-x", source_job_id="j-2", fingerprint="fp", content_hash="a")
    assert store_conn.execute("SELECT COUNT(*) FROM posting_aliases").fetchone()[0] == 1

    _upsert(store_conn, posting_id="p-b", source_job_id="j-2", fingerprint="fp", content_hash="b")

    assert _canonical(store_conn) == {"p-a", "p-b"}
    assert store_conn.execute("SELECT COUNT(*) FROM posting_aliases").fetchone()[0] == 0


def test_an_edit_that_makes_two_postings_identical_leaves_one(
    store_conn: sqlite3.Connection,
) -> None:
    _upsert(store_conn, posting_id="p-a", source_job_id="j-1", fingerprint="fp", content_hash="a")
    _upsert(store_conn, posting_id="p-b", source_job_id="j-2", fingerprint="fp", content_hash="b")
    _upsert(store_conn, posting_id="p-b", source_job_id="j-2", fingerprint="fp", content_hash="a")
    assert _canonical(store_conn) == {"p-a"}


def _application(conn: sqlite3.Connection, posting_id: str) -> None:
    now = "2026-10-30T00:00:00+00:00"
    conn.execute(
        "INSERT INTO applications (application_id, company, status, posting_id, origin, "
        "created_at, updated_at) VALUES ('app', 'Acme', 'applied', ?, 'feed', ?, ?)",
        (posting_id, now, now),
    )


def test_a_takeover_carries_the_application_with_the_posting(
    store_conn: sqlite3.Connection,
) -> None:
    _upsert(store_conn, posting_id="p-old", source_job_id="j-1", fingerprint="fp")
    _application(store_conn, "p-old")
    deactivate_missing(store_conn, Source.GREENHOUSE, "acme", {"j-other"})
    _upsert(store_conn, posting_id="p-new", source_job_id="j-2", fingerprint="fp")
    row = store_conn.execute("SELECT posting_id FROM applications").fetchone()
    assert row["posting_id"] == "p-new"


def _two_rows(conn: sqlite3.Connection, **shared: object) -> None:
    """Two identical live rows, as the old identity branch could leave them."""
    _upsert(conn, posting_id="p-a", source_job_id="j-1", fingerprint="fp", content_hash="a")
    _upsert(conn, posting_id="p-b", source_job_id="j-2", fingerprint="fp", content_hash="b")
    conn.execute(
        "UPDATE postings SET content_hash = 'same', score = CASE posting_id WHEN 'p-b' THEN 80 "
        "ELSE 10 END",
    )
    if shared:
        conn.execute("UPDATE postings SET location_raw = ?", (shared["location_raw"],))


def test_identical_rows_merge_into_the_best_one_and_follow_it(
    store_conn: sqlite3.Connection,
) -> None:
    _two_rows(store_conn)
    _application(store_conn, "p-a")
    ((group), *_), left_alone = find_duplicates(store_conn)
    assert (group.keep, group.drop, left_alone) == ("p-b", ("p-a",), [])

    merge_duplicates(store_conn, group)

    assert _canonical(store_conn) == {"p-b"}
    aliases = store_conn.execute("SELECT source_job_id, canonical_id FROM posting_aliases")
    assert [tuple(row) for row in aliases] == [("j-1", "p-b")]
    row = store_conn.execute("SELECT posting_id FROM applications").fetchone()
    assert row["posting_id"] == "p-b"


def test_the_row_the_user_marked_is_the_one_kept(store_conn: sqlite3.Connection) -> None:
    _two_rows(store_conn)
    mark_favorite(store_conn, "p-a", True)
    groups, _ = find_duplicates(store_conn)
    assert groups[0].keep == "p-a"


def test_two_rows_the_user_marked_are_never_merged(store_conn: sqlite3.Connection) -> None:
    _two_rows(store_conn)
    mark_favorite(store_conn, "p-a", True)
    mark_favorite(store_conn, "p-b", True)
    groups, left_alone = find_duplicates(store_conn)
    assert groups == []
    assert [set(ids) for ids in left_alone] == [{"p-a", "p-b"}]


def test_counted_locations_are_not_known_to_be_the_same_place(
    store_conn: sqlite3.Connection,
) -> None:
    _two_rows(store_conn, location_raw="3 Locations")
    assert find_duplicates(store_conn) == ([], [])
