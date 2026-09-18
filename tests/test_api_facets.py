"""`/facets` contract tests — invariant I6, blueprint/wp/WP07-api.md §4, §8."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.enums import RemoteMode
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
