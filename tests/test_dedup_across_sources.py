"""WP13 §2 — the prerequisite: the same posting from several sources appears once.

"Ne pas allumer un agrégateur avant que le dédoublonnage soit implémenté et testé."
These go through `ingest`, the real pipeline, with postings from the source
*families* (the aggregator collectors themselves are not needed — and these tests
must survive `rm -rf collect/aggregators/`).
"""

import sqlite3
from datetime import UTC, datetime

import pytest

from factories_store import make_board
from jobtracker.core.enums import Source
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import RawPosting
from jobtracker.match.profile import Profile, build_profile
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.runtime.pipeline import ingest
from jobtracker.store.companies import sync_companies
from test_runtime_pipeline import _PROFILE_DATA

pytestmark = pytest.mark.db

_DESCRIPTION = "Join our trading team and build low latency systems. " * 4


@pytest.fixture
def profile() -> Profile:
    return build_profile(_PROFILE_DATA)


@pytest.fixture(autouse=True)
def _company(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    store_conn.commit()


def _raw(source: Source, job_id: str, **overrides: object) -> RawPosting:
    base: dict[str, object] = {
        "source": source,
        "company_slug": "acme",
        "source_job_id": job_id,
        "url": f"https://{source.value}.example/{job_id}",
        "title_raw": "Quantitative Developer",
        "description_raw": _DESCRIPTION,
        "location_raw": "Paris, France",
        "department_raw": None,
        "posted_at_raw": "2026-01-01T00:00:00Z",
        "payload": b"{}",
        "fetched_at": datetime(2026, 1, 1, tzinfo=UTC),
        "content_hash": f"hash-{source.value}-{job_id}",
    }
    base.update(overrides)
    return RawPosting(**base)  # type: ignore[arg-type]


def _ingest(
    conn: sqlite3.Connection, raw: RawPosting, taxonomy: Taxonomy, geo: GeoIndex, p: Profile
):
    return ingest(conn, raw, taxonomy=taxonomy, geo=geo, profile=p, hq_country="FR")


def _canonicals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT posting_id, source FROM postings WHERE is_canonical = 1").fetchall()


def test_the_same_posting_from_an_ats_and_an_aggregator_is_one_posting_and_an_alias(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    ats = _ingest(store_conn, _raw(Source.GREENHOUSE, "gh-1"), taxonomy, geo_index, profile)
    agg = _ingest(store_conn, _raw(Source.LINKEDIN, "li-1"), taxonomy, geo_index, profile)

    assert (ats.outcome, agg.outcome) == ("new", "aliased")
    assert agg.posting_id == ats.posting_id
    assert len(_canonicals(store_conn)) == 1
    aliases = store_conn.execute("SELECT source FROM posting_aliases").fetchall()
    assert [a["source"] for a in aliases] == ["linkedin"]


def test_the_same_posting_from_three_aggregators_is_one_posting_and_three_aliases(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    ats = _ingest(store_conn, _raw(Source.GREENHOUSE, "gh-1"), taxonomy, geo_index, profile)
    for source in (Source.EFC, Source.INDEED, Source.ADZUNA):
        outcome = _ingest(
            store_conn, _raw(source, f"{source.value}-1"), taxonomy, geo_index, profile
        )
        assert outcome.outcome == "aliased"
    assert len(_canonicals(store_conn)) == 1
    assert store_conn.execute("SELECT COUNT(*) AS n FROM posting_aliases").fetchone()["n"] == 3
    assert _canonicals(store_conn)[0]["posting_id"] == ats.posting_id


def test_an_ats_posting_takes_over_from_an_aggregator_that_saw_it_first(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    _ingest(store_conn, _raw(Source.INDEED, "in-1"), taxonomy, geo_index, profile)
    _ingest(store_conn, _raw(Source.GREENHOUSE, "gh-1"), taxonomy, geo_index, profile)

    (canonical,) = _canonicals(store_conn)
    assert canonical["source"] == "greenhouse"  # the ATS carries the real apply URL (ADR-004)
    assert store_conn.execute("SELECT COUNT(*) AS n FROM posting_aliases").fetchone()["n"] == 1


def test_a_different_employer_with_the_same_title_is_not_merged(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    _ingest(store_conn, _raw(Source.GREENHOUSE, "gh-1"), taxonomy, geo_index, profile)
    other = _raw(Source.LINKEDIN, "li-9", company_slug="other_corp", company_name="Other Corp")
    outcome = _ingest(store_conn, other, taxonomy, geo_index, profile)
    assert outcome.outcome == "new"
    assert len(_canonicals(store_conn)) == 2
