"""`/companies` contract tests — blueprint/03-INTERFACES.md §3.6."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from factories_store import make_board, make_posting, make_verdict
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting

pytestmark = pytest.mark.db


def test_lists_companies_with_their_posting_count(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    sync_companies(api_conn, [make_board(company_slug="acme", sector="prop_trading")])
    posting = make_posting()
    upsert_posting(api_conn, posting, make_verdict())
    api_conn.commit()

    resp = api_client.get("/companies")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["company_slug"] == "acme"
    assert body[0]["postings_count"] == 1


def test_filters_by_sector(api_client: TestClient, api_conn: sqlite3.Connection) -> None:
    sync_companies(
        api_conn,
        [
            make_board(company_slug="a", sector="prop_trading"),
            make_board(company_slug="b", sector="bank"),
        ],
    )
    resp = api_client.get("/companies", params={"sector": "bank"})
    assert [c["company_slug"] for c in resp.json()] == ["b"]
