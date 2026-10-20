"""Tracks end to end: the pass, the feed, the API — blueprint/wp/WP20-tracks.md §3-5."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.enums import RemoteMode, RoleFamily, Tier, Track
from jobtracker.core.models import Location, Posting
from jobtracker.match.profile import Profile, load_tracks
from jobtracker.runtime.tracks import score_tracks
from jobtracker.store.companies import sync_companies
from jobtracker.store.facets import facet_counts
from jobtracker.store.postings import (
    PostingFilter,
    SortKey,
    get_posting_row,
    list_postings,
    update_resolution,
    upsert_posting,
)
from jobtracker.store.tracks import get_track_verdict

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("frozen_clock")]

CONFIGS = Path(__file__).resolve().parent.parent / "configs"
CH = Track.CH_TECH


def _place(city: str, country: str) -> tuple[Location, ...]:
    return (
        Location(city=city, country=country, region=None, remote_mode=RemoteMode.ONSITE, raw=city),
    )


@pytest.fixture
def tracks() -> dict[Track, Profile]:
    return load_tracks(
        CONFIGS / "profile.yaml",
        CONFIGS / "tracks.yaml",
        company_tiers={"acme": 2},
        company_sectors={"acme": "tech"},
    )


def _seed(conn: sqlite3.Connection, n: int, **overrides: object) -> str:
    posting = make_posting(
        posting_id=f"01J00000000000000000000P{n}",
        fingerprint=f"fp-{n}",
        source_job_id=f"job-{n}",
        **overrides,
    )
    # The quant verdict a tech employer gets: rejected off topic.
    verdict = make_verdict(
        posting_id=posting.posting_id, score=0, tier=Tier.REJECTED, rejection_reason="off_topic"
    )
    posting_id = upsert_posting(conn, posting, verdict)
    conn.commit()
    return posting_id


@pytest.fixture
def seeded(store_conn: sqlite3.Connection) -> dict[str, str]:
    sync_companies(store_conn, [make_board(sector="tech", priority=2)])
    return {
        "cuda": _seed(
            store_conn,
            1,
            title="CUDA Engineer",
            tech=frozenset({"cpp", "cuda"}),
            locations=_place("Zurich", "CH"),
        ),
        "java": _seed(
            store_conn,
            2,
            title="Java Developer",
            tech=frozenset({"java"}),
            locations=_place("Zurich", "CH"),
        ),
        "paris": _seed(
            store_conn,
            3,
            title="C++ Engineer",
            tech=frozenset({"cpp"}),
            locations=_place("Paris", "FR"),
        ),
        "generic": _seed(
            store_conn,
            4,
            title="Software Engineer",
            tech=frozenset({"python"}),
            locations=_place("Lausanne", "CH"),
        ),
    }


# --- the pass -------------------------------------------------------------------------------


def test_the_pass_scores_swiss_postings_only(
    store_conn: sqlite3.Connection, seeded: dict[str, str], tracks: dict[Track, Profile]
) -> None:
    (result,) = score_tracks(store_conn, tracks)

    assert result.scored == 3  # the Paris one is out of scope: no row, not a rejection
    assert get_track_verdict(store_conn, CH, seeded["paris"]) is None
    cuda = get_track_verdict(store_conn, CH, seeded["cuda"])
    java = get_track_verdict(store_conn, CH, seeded["java"])
    assert cuda is not None and cuda.tier != Tier.REJECTED
    assert java is not None and java.rejection_reason == "off_topic"


def test_a_second_pass_with_nothing_new_scores_nothing(
    store_conn: sqlite3.Connection, seeded: dict[str, str], tracks: dict[Track, Profile]
) -> None:
    score_tracks(store_conn, tracks)
    (again,) = score_tracks(store_conn, tracks)
    assert again.scored == 0
    assert again.dropped == 0


def test_a_quant_rescore_makes_the_track_rescore(
    store_conn: sqlite3.Connection, seeded: dict[str, str], tracks: dict[Track, Profile]
) -> None:
    score_tracks(store_conn, tracks)
    later = datetime(2026, 1, 2, tzinfo=UTC)
    store_conn.execute(
        "UPDATE verdicts SET scored_at = ? WHERE posting_id = ?",
        (later.isoformat(), seeded["java"]),
    )
    store_conn.commit()

    (result,) = score_tracks(store_conn, tracks)

    assert result.scored == 1


def test_a_posting_that_leaves_switzerland_leaves_the_track(
    store_conn: sqlite3.Connection, seeded: dict[str, str], tracks: dict[Track, Profile]
) -> None:
    score_tracks(store_conn, tracks)
    moved: Posting = make_posting(
        posting_id=seeded["cuda"],
        fingerprint="fp-1",
        source_job_id="job-1",
        title="CUDA Engineer",
        locations=_place("Paris", "FR"),
    )
    update_resolution(
        store_conn,
        moved,
        make_verdict(
            posting_id=seeded["cuda"], score=0, tier=Tier.REJECTED, rejection_reason="off_topic"
        ),
    )
    store_conn.commit()

    (result,) = score_tracks(store_conn, tracks)

    assert result.dropped == 1
    assert get_track_verdict(store_conn, CH, seeded["cuda"]) is None


def test_a_track_removed_from_the_config_takes_its_rows(
    store_conn: sqlite3.Connection, seeded: dict[str, str], tracks: dict[Track, Profile]
) -> None:
    score_tracks(store_conn, tracks)
    score_tracks(store_conn, {})
    assert store_conn.execute("SELECT COUNT(*) FROM track_verdicts").fetchone()[0] == 0


# --- the feed -------------------------------------------------------------------------------


def test_the_track_feed_lists_its_own_postings_with_its_own_score(
    store_conn: sqlite3.Connection, seeded: dict[str, str], tracks: dict[Track, Profile]
) -> None:
    score_tracks(store_conn, tracks)
    shown = frozenset({Tier.STRONG, Tier.POSSIBLE, Tier.STRETCH})

    quant = list_postings(store_conn, PostingFilter(tiers=shown), SortKey.SCORE, None, 50)
    track = list_postings(store_conn, PostingFilter(tiers=shown, track=CH), SortKey.SCORE, None, 50)

    assert quant.items == ()  # every one of them is off topic for the quant feed
    ids = [row.posting_id for row in track.items]
    assert seeded["cuda"] in ids
    assert seeded["java"] not in ids and seeded["paris"] not in ids
    cuda = next(row for row in track.items if row.posting_id == seeded["cuda"])
    assert cuda.score == get_track_verdict(store_conn, CH, seeded["cuda"]).score  # type: ignore[union-attr]
    assert [row.score for row in track.items] == sorted(
        (row.score for row in track.items), reverse=True
    )


def test_the_track_feed_paginates_on_the_track_score(
    store_conn: sqlite3.Connection, seeded: dict[str, str], tracks: dict[Track, Profile]
) -> None:
    score_tracks(store_conn, tracks)
    flt = PostingFilter(track=CH)  # every tier, rejected included: three rows
    first = list_postings(store_conn, flt, SortKey.SCORE, None, 1)
    seen = [row.posting_id for row in first.items]
    cursor = first.next_cursor
    while cursor is not None:
        page = list_postings(store_conn, flt, SortKey.SCORE, cursor, 1)
        seen += [row.posting_id for row in page.items]
        cursor = page.next_cursor
    assert sorted(seen) == sorted([seeded["cuda"], seeded["java"], seeded["generic"]])


def test_track_facets_count_the_track_rejection_reasons(
    store_conn: sqlite3.Connection, seeded: dict[str, str], tracks: dict[Track, Profile]
) -> None:
    score_tracks(store_conn, tracks)
    rejected = frozenset({Tier.REJECTED})
    counts = facet_counts(store_conn, PostingFilter(tiers=rejected, track=CH))
    assert counts.rejection_reasons == {"off_topic": 2}  # Java, a Python-only role; not Paris
    assert "FR" not in counts.countries


def test_the_detail_row_carries_the_track_score_and_falls_back_to_quant(
    store_conn: sqlite3.Connection, seeded: dict[str, str], tracks: dict[Track, Profile]
) -> None:
    score_tracks(store_conn, tracks)
    with_track = get_posting_row(store_conn, seeded["cuda"], track=CH)
    paris = get_posting_row(store_conn, seeded["paris"], track=CH)
    assert with_track is not None and with_track.tier != Tier.REJECTED
    assert paris is not None and paris.rejection_reason == "off_topic"  # the quant verdict


# --- the API --------------------------------------------------------------------------------


def test_api_track_param_reaches_feed_detail_and_facets(
    api_client: TestClient, api_conn: sqlite3.Connection, tracks: dict[Track, Profile]
) -> None:
    sync_companies(api_conn, [make_board(sector="tech", priority=2)])
    cuda = _seed(
        api_conn,
        1,
        title="CUDA Engineer",
        tech=frozenset({"cuda"}),
        locations=_place("Zurich", "CH"),
    )
    score_tracks(api_conn, tracks)

    feed = api_client.get("/postings", params={"track": "ch_tech"}).json()
    assert [item["posting_id"] for item in feed["items"]] == [cuda]
    assert api_client.get("/postings").json()["items"] == []

    detail = api_client.get(f"/postings/{cuda}", params={"track": "ch_tech"}).json()
    assert detail["tier"] != "rejected"
    assert "title_strong" in {r["code"] for r in detail["reasons"]}

    facets = api_client.get("/facets", params={"track": "ch_tech"}).json()
    assert facets["countries"] == {"CH": 1}


def test_api_unknown_track_is_a_422(api_client: TestClient) -> None:
    assert api_client.get("/postings", params={"track": "mars_tech"}).status_code == 422


def test_role_family_other_never_reaches_the_track_feed(
    store_conn: sqlite3.Connection, tracks: dict[Track, Profile]
) -> None:
    sync_companies(store_conn, [make_board(sector="tech", priority=2)])
    sales = _seed(
        store_conn,
        5,
        title="C++ Sales Engineer",
        role_family=RoleFamily.OTHER,
        tech=frozenset({"cpp"}),
        locations=_place("Zurich", "CH"),
    )
    score_tracks(store_conn, tracks)
    verdict = get_track_verdict(store_conn, CH, sales)
    assert verdict is not None and verdict.tier == Tier.REJECTED
