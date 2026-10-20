"""`/facets` contract tests — invariant I6, blueprint/wp/WP07-api.md §4, §8."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.enums import RemoteMode, Tier
from jobtracker.core.models import Location
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting

pytestmark = pytest.mark.db


def _seed_two_countries(conn: sqlite3.Connection) -> None:
    sync_companies(conn, [make_board()])
    fr = make_posting(
        posting_id="p-fr",
        source_job_id="j-fr",
        fingerprint="fp-fr",
        locations=(
            Location(
                city="Paris", country="FR", region=None, remote_mode=RemoteMode.ONSITE, raw="Paris"
            ),
        ),
    )
    gb = make_posting(
        posting_id="p-gb",
        source_job_id="j-gb",
        fingerprint="fp-gb",
        locations=(
            Location(
                city="London",
                country="GB",
                region=None,
                remote_mode=RemoteMode.ONSITE,
                raw="London",
            ),
        ),
    )
    upsert_posting(conn, fr, make_verdict(posting_id="p-fr"))
    upsert_posting(conn, gb, make_verdict(posting_id="p-gb"))
    conn.commit()


def test_facets_on_an_empty_feed(api_client: TestClient) -> None:
    resp = api_client.get("/facets")
    assert resp.status_code == 200
    assert resp.json()["countries"] == {}


def test_selecting_one_country_does_not_zero_out_the_others(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    _seed_two_countries(api_conn)

    resp = api_client.get("/facets", params={"countries": "FR"})
    counts = resp.json()["countries"]

    assert counts["FR"] == 1
    assert counts["GB"] == 1  # invariant I6: not collapsed by its own filter


def test_postings_and_facets_agree_under_the_same_filter(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    _seed_two_countries(api_conn)

    postings = api_client.get("/postings", params={"countries": "FR"}).json()
    facets = api_client.get("/facets", params={"countries": "FR"}).json()

    assert len(postings["items"]) == facets["countries"]["FR"]


def test_rejection_reasons_are_counted_without_their_own_filter(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    sync_companies(api_conn, [make_board()])
    for posting_id, reason in (("p-a", "senior_only"), ("p-b", "not_quant"), ("p-c", "not_quant")):
        posting = make_posting(
            posting_id=posting_id, source_job_id=f"j-{posting_id}", fingerprint=f"fp-{posting_id}"
        )
        verdict = make_verdict(
            posting_id=posting_id, score=0, tier=Tier.REJECTED, rejection_reason=reason
        )
        upsert_posting(api_conn, posting, verdict)
    api_conn.commit()

    assert api_client.get("/facets").json()["rejection_reasons"] == {}
    resp = api_client.get(
        "/facets", params={"tiers": "rejected", "rejection_reasons": "senior_only"}
    )
    assert resp.json()["rejection_reasons"] == {"senior_only": 1, "not_quant": 2}
