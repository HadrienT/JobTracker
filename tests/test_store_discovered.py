"""Employers seen only at an aggregator — migration 0004, WP13 §4."""

import sqlite3
from datetime import UTC, datetime

import pytest

from factories_store import make_board
from jobtracker.core.enums import Source
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import RawPosting
from jobtracker.match.profile import build_profile
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.runtime.pipeline import ingest
from jobtracker.store.companies import list_companies, list_discovered, sync_companies
from test_runtime_pipeline import _PROFILE_DATA

pytestmark = pytest.mark.db


def _raw(**overrides: object) -> RawPosting:
    base: dict[str, object] = {
        "source": Source.EFC,
        "company_slug": "oxford_knight",
        "company_name": "Oxford Knight",
        "source_job_id": "1",
        "url": "https://efc.example/1",
        "title_raw": "Quantitative Developer",
        "description_raw": "Build pricing libraries. " * 10,
        "location_raw": "London, United Kingdom",
        "department_raw": None,
        "posted_at_raw": None,
        "payload": b"{}",
        "fetched_at": datetime(2026, 1, 1, tzinfo=UTC),
        "content_hash": "h1",
    }
    base.update(overrides)
    return RawPosting(**base)  # type: ignore[arg-type]


def _ingest(conn: sqlite3.Connection, raw: RawPosting, taxonomy: Taxonomy, geo: GeoIndex) -> None:
    ingest(
        conn, raw, taxonomy=taxonomy, geo=geo, profile=build_profile(_PROFILE_DATA), hq_country="GB"
    )


def test_an_unknown_employer_gets_a_row_instead_of_breaking_the_foreign_key(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex
) -> None:
    sync_companies(store_conn, [make_board()])
    _ingest(store_conn, _raw(), taxonomy, geo_index)  # would raise IntegrityError without the row

    assert list_discovered(store_conn) == [("oxford_knight", "Oxford Knight", 1)]


def test_the_startup_registry_sync_does_not_sweep_discovered_employers_away(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex
) -> None:
    sync_companies(store_conn, [make_board()])
    _ingest(store_conn, _raw(), taxonomy, geo_index)
    sync_companies(store_conn, [make_board()])  # what every process start does
    assert [slug for slug, _, _ in list_discovered(store_conn)] == ["oxford_knight"]


def test_discovered_employers_stay_out_of_the_registry_views(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex
) -> None:
    sync_companies(store_conn, [make_board()])
    _ingest(store_conn, _raw(), taxonomy, geo_index)
    # /companies and the watchdog must not report an employer we never registered as "mute".
    assert [c.company_slug for c in list_companies(store_conn)] == ["acme"]
    assert len(list_companies(store_conn, include_discovered=True)) == 2


def test_adding_the_employer_to_the_registry_ends_its_discovered_status(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex
) -> None:
    sync_companies(store_conn, [make_board()])
    _ingest(store_conn, _raw(), taxonomy, geo_index)
    sync_companies(
        store_conn,
        [make_board(), make_board(company_slug="oxford_knight", company_name="Oxford Knight")],
    )
    assert list_discovered(store_conn) == []  # WP00 did its job; the report empties out


def test_an_ats_posting_never_creates_a_discovered_row(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex
) -> None:
    sync_companies(store_conn, [make_board()])
    ats = _raw(source=Source.GREENHOUSE, company_slug="acme", company_name=None)
    _ingest(store_conn, ats, taxonomy, geo_index)
    assert list_discovered(store_conn) == []
