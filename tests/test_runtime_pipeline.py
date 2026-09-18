"""`runtime.pipeline.ingest` contract tests — blueprint/05-SEQUENCES.md §1."""

import sqlite3
from datetime import UTC, datetime

import pytest

from factories_store import make_board
from jobtracker.core.enums import Source
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import RawPosting
from jobtracker.match.profile import Profile, build_profile
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.runtime import pipeline
from jobtracker.runtime.pipeline import ingest
from jobtracker.store.archive import has_payload, read_payload
from jobtracker.store.companies import sync_companies

pytestmark = pytest.mark.db

_PROFILE_DATA = {
    "version": 1,
    "titles": {"strong": ["quant developer"], "possible": ["software engineer"], "excluded": []},
    "seniority": {"accept_if_years_max": 3, "reject": ["senior", "lead"]},
    "hard_rejects": {"phd_required": True, "min_years_above": 4, "stale_after_days": 60},
    "weights": {
        "title_strong": 35,
        "title_possible": 18,
        "sector_tier1": 12,
        "tech_cpp": 10,
        "tech_python": 6,
        "tech_niche": 8,
        "seniority_match": 20,
        "graduate_programme": 10,
        "visa_sponsors": 8,
        "visa_no": -25,
        "salary_disclosed": 3,
        "freshness_7d": 6,
        "stale_penalty": -10,
    },
    "tiers": {"strong": 70, "possible": 45, "stretch": 25},
}


@pytest.fixture
def profile() -> Profile:
    return build_profile(_PROFILE_DATA)


@pytest.fixture(autouse=True)
def _company(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    store_conn.commit()


def _raw(**overrides: object) -> RawPosting:
    base: dict[str, object] = {
        "source": Source.GREENHOUSE,
        "company_slug": "acme",
        "source_job_id": "job-1",
        "url": "https://example.com/jobs/1",
        "title_raw": "Quant Developer",
        "description_raw": "Join our trading team. C++ required.",
        "location_raw": "Paris, France",
        "department_raw": None,
        "posted_at_raw": None,
        "payload": b'{"id": "job-1"}',
        "fetched_at": datetime(2026, 1, 1, tzinfo=UTC),
        "content_hash": "hash-1",
    }
    base.update(overrides)
    return RawPosting(**base)  # type: ignore[arg-type]


def test_a_new_posting_is_stored_as_new(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    result = ingest(store_conn, _raw(), taxonomy=taxonomy, geo=geo_index, profile=profile)
    assert result.outcome == "new"
    assert result.posting_id is not None
    row = store_conn.execute(
        "SELECT title FROM postings WHERE posting_id = ?", (result.posting_id,)
    ).fetchone()
    assert row["title"] == "Quant Developer"


def test_the_payload_is_archived_before_normalize_is_even_called(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*args: object, **kwargs: object) -> None:
        raise ValueError("the normalizer choked on this one")

    monkeypatch.setattr(pipeline, "normalize", _boom)

    raw = _raw(payload=b"exotic payload bytes")
    result = ingest(store_conn, raw, taxonomy=taxonomy, geo=geo_index, profile=profile)

    assert result.outcome == "normalize_error"
    assert result.posting_id is not None
    assert has_payload(store_conn, result.posting_id)
    assert read_payload(store_conn, result.posting_id) == b"exotic payload bytes"
    # And the posting row itself was never created — the crash only ever
    # touches raw_payloads, never a half-written postings row.
    assert (
        store_conn.execute(
            "SELECT 1 FROM postings WHERE posting_id = ?", (result.posting_id,)
        ).fetchone()
        is None
    )


def test_reingesting_the_same_content_is_updated_not_new(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    first = ingest(store_conn, _raw(), taxonomy=taxonomy, geo=geo_index, profile=profile)
    second = ingest(
        store_conn,
        _raw(title_raw="Quant Developer II"),
        taxonomy=taxonomy,
        geo=geo_index,
        profile=profile,
    )
    assert first.outcome == "new"
    assert second.outcome == "updated"
    assert second.posting_id == first.posting_id


def test_an_alias_never_reaches_match_evaluate(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A second ATS posting sharing a fingerprint with an existing canonical
    # one must become an alias — and must never call evaluate() at all
    # (blueprint/wp/WP08-runtime.md §2: dedup precedes scoring).
    first = ingest(store_conn, _raw(), taxonomy=taxonomy, geo=geo_index, profile=profile)
    assert first.outcome == "new"

    called = False

    def _fail_if_called(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("evaluate() must not be called for an alias")

    monkeypatch.setattr(pipeline, "evaluate", _fail_if_called)

    duplicate = _raw(source_job_id="job-2", content_hash="hash-2")
    result = ingest(store_conn, duplicate, taxonomy=taxonomy, geo=geo_index, profile=profile)

    assert called is False
    assert result.outcome == "aliased"
    assert result.posting_id == first.posting_id
