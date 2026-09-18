"""`/postings` contract tests — blueprint/wp/WP07-api.md §3, §8."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.enums import RemoteMode, RoleFamily, VisaStatus
from jobtracker.core.models import Location, Reason
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting
from jobtracker.store.search import index_description

pytestmark = pytest.mark.db


def _seed(conn: sqlite3.Connection, **overrides: object) -> str:
    sync_companies(conn, [make_board()])
    posting = make_posting(**overrides)
    posting_id = upsert_posting(conn, posting, make_verdict(posting_id=posting.posting_id))
    conn.commit()
    return posting_id


def test_empty_feed_returns_an_empty_page(api_client: TestClient) -> None:
    resp = api_client.get("/postings")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "next_cursor": None}


def test_a_seeded_posting_comes_back_with_the_public_shape(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    posting_id = _seed(api_conn)
    resp = api_client.get("/postings")
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["posting_id"] == posting_id
    assert item["company_name"] == "Acme"
    assert "posting_id" in item and "score" in item and "tier" in item


def test_visa_unknown_is_included_by_default(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    _seed(api_conn, visa_sponsorship=VisaStatus.UNKNOWN)
    resp = api_client.get("/postings")
    assert len(resp.json()["items"]) == 1


def test_visa_no_is_excluded_by_default(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    _seed(api_conn, visa_sponsorship=VisaStatus.NO)
    resp = api_client.get("/postings")
    assert resp.json()["items"] == []


def test_role_family_filter_restricts_the_result(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    sync_companies(api_conn, [make_board()])
    dev = make_posting(
        posting_id="p-dev",
        source_job_id="j-dev",
        fingerprint="fp-dev",
        role_family=RoleFamily.QUANT_DEV,
    )
    trading = make_posting(
        posting_id="p-trading",
        source_job_id="j-trading",
        fingerprint="fp-trading",
        role_family=RoleFamily.QUANT_TRADING,
    )
    upsert_posting(api_conn, dev, make_verdict(posting_id="p-dev"))
    upsert_posting(api_conn, trading, make_verdict(posting_id="p-trading"))
    api_conn.commit()

    resp = api_client.get("/postings", params={"role_families": "quant_dev"})
    assert [i["posting_id"] for i in resp.json()["items"]] == ["p-dev"]


def test_country_filter_restricts_the_result(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    sync_companies(api_conn, [make_board()])
    paris = make_posting(
        posting_id="p-paris",
        source_job_id="j-paris",
        fingerprint="fp-paris",
        locations=(
            Location(
                city="Paris", country="FR", region=None, remote_mode=RemoteMode.ONSITE, raw="Paris"
            ),
        ),
    )
    london = make_posting(
        posting_id="p-london",
        source_job_id="j-london",
        fingerprint="fp-london",
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
    upsert_posting(api_conn, paris, make_verdict(posting_id="p-paris"))
    upsert_posting(api_conn, london, make_verdict(posting_id="p-london"))
    api_conn.commit()

    resp = api_client.get("/postings", params={"countries": "FR"})
    assert [i["posting_id"] for i in resp.json()["items"]] == ["p-paris"]


def test_every_filter_combined_returns_no_sql_error(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    _seed(api_conn)
    resp = api_client.get(
        "/postings",
        params={
            "countries": ["FR", "GB"],
            "cities": ["Paris"],
            "companies": ["acme"],
            "sectors": ["prop_trading"],
            "sources": ["greenhouse"],
            "role_families": ["quant_dev"],
            "seniorities": ["junior"],
            "remote_modes": ["onsite"],
            "tech_all": ["python"],
            "tech_any": ["python", "cpp"],
            "visa": ["sponsors", "unknown", "no"],
            "min_score": 0,
            "tiers": ["strong", "possible", "stretch", "rejected"],
            "posted_within_days": 30,
            "query": "developer",
            "favorites_only": False,
            "include_hidden": True,
            "sort": "posted",
            "limit": 10,
        },
    )
    assert resp.status_code == 200


def test_limit_above_100_is_silently_clamped(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    _seed(api_conn)
    resp = api_client.get("/postings", params={"limit": 5000})
    assert resp.status_code == 200


def test_corrupted_cursor_is_a_400(api_client: TestClient) -> None:
    resp = api_client.get("/postings", params={"cursor": "not-valid-base64!!"})
    assert resp.status_code == 400


def test_pagination_of_500_postings_has_no_gap_and_no_duplicate(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    sync_companies(api_conn, [make_board()])
    for i in range(500):
        posting = make_posting(
            posting_id=f"p-{i:04d}", source_job_id=f"j-{i}", fingerprint=f"fp-{i}"
        )
        upsert_posting(api_conn, posting, make_verdict(posting_id=f"p-{i:04d}", score=i % 100))
    api_conn.commit()

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        resp = api_client.get(
            "/postings", params={"limit": 50, **({"cursor": cursor} if cursor else {})}
        )
        body = resp.json()
        seen.extend(item["posting_id"] for item in body["items"])
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert pages == 10
    assert len(seen) == 500
    assert len(set(seen)) == 500


def test_detail_route_includes_description_and_reasons(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    sync_companies(api_conn, [make_board()])
    posting = make_posting()
    verdict = make_verdict(
        posting_id=posting.posting_id,
        reasons=(Reason(code="title_strong", delta=35, evidence="Quant Developer"),),
    )
    upsert_posting(api_conn, posting, verdict)
    index_description(api_conn, posting.posting_id, "Full description text.")
    api_conn.commit()

    resp = api_client.get(f"/postings/{posting.posting_id}")
    body = resp.json()
    assert body["description"] == "Full description text."
    assert body["reasons"][0]["code"] == "title_strong"
    assert body["aliases"] == []


def test_detail_route_404s_for_an_unknown_id(api_client: TestClient) -> None:
    resp = api_client.get("/postings/does-not-exist")
    assert resp.status_code == 404


def test_favorite_then_pipeline_replay_keeps_the_favorite(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    posting_id = _seed(api_conn)

    resp = api_client.post(f"/postings/{posting_id}/favorite", json={"value": True})
    assert resp.status_code == 204

    # A pipeline "replay": the same posting re-upserted with fresh content.
    posting = make_posting(
        posting_id=posting_id, title="Quant Developer II", content_hash="new-hash"
    )
    upsert_posting(api_conn, posting, make_verdict(posting_id=posting_id))
    api_conn.commit()

    resp = api_client.get("/postings")
    assert resp.json()["items"][0]["favorited"] is True


def test_favorite_on_an_unknown_posting_is_a_404(api_client: TestClient) -> None:
    resp = api_client.post("/postings/does-not-exist/favorite", json={"value": True})
    assert resp.status_code == 404


def test_hide_removes_from_the_default_feed(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    posting_id = _seed(api_conn)
    resp = api_client.post(f"/postings/{posting_id}/hide", json={"value": True})
    assert resp.status_code == 204
    assert api_client.get("/postings").json()["items"] == []
    assert len(api_client.get("/postings", params={"include_hidden": True}).json()["items"]) == 1
