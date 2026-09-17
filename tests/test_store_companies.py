import sqlite3

import pytest

from factories_store import make_board
from jobtracker.store.companies import (
    get_company,
    list_companies,
    record_run_result,
    sync_companies,
)

pytestmark = pytest.mark.db


def test_sync_companies_inserts_and_updates(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board(company_slug="acme", company_name="Acme")])
    store_conn.commit()
    assert get_company(store_conn, "acme").company_name == "Acme"  # type: ignore[union-attr]

    sync_companies(store_conn, [make_board(company_slug="acme", company_name="Acme Renamed")])
    store_conn.commit()
    assert get_company(store_conn, "acme").company_name == "Acme Renamed"  # type: ignore[union-attr]


def test_sync_companies_removes_slugs_no_longer_in_the_config(
    store_conn: sqlite3.Connection,
) -> None:
    sync_companies(store_conn, [make_board(company_slug="acme"), make_board(company_slug="other")])
    store_conn.commit()

    sync_companies(store_conn, [make_board(company_slug="acme")])
    store_conn.commit()

    assert get_company(store_conn, "other") is None
    assert get_company(store_conn, "acme") is not None


def test_sync_companies_preserves_health_counters(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board(company_slug="acme")])
    store_conn.commit()
    record_run_result(store_conn, "acme", ok_at="2026-01-01T00:00:00+00:00", count=42)
    store_conn.commit()

    sync_companies(store_conn, [make_board(company_slug="acme", company_name="Acme v2")])
    store_conn.commit()

    company = get_company(store_conn, "acme")
    assert company is not None
    assert company.last_count == 42
    assert company.company_name == "Acme v2"


def test_list_companies_filters_by_sector_and_country(store_conn: sqlite3.Connection) -> None:
    sync_companies(
        store_conn,
        [
            make_board(company_slug="a", sector="prop_trading", hq_country="US"),
            make_board(company_slug="b", sector="bank", hq_country="FR"),
        ],
    )
    store_conn.commit()

    assert [c.company_slug for c in list_companies(store_conn, sector="bank")] == ["b"]
    assert [c.company_slug for c in list_companies(store_conn, country="US")] == ["a"]
