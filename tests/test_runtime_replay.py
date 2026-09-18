"""`jobtracker replay` — blueprint/wp/WP16-feedback.md §2, §6.

The two halves of every scenario use the *same* real `normalize`, with one side
deliberately handicapped, so "an improvement" and "a regression" are the
genuine article rather than a mocked report.
"""

import sqlite3
from datetime import UTC, datetime

import pytest

from factories_store import make_board
from jobtracker.core.enums import RoleFamily, Seniority, Source
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import Location, Posting, RawPosting
from jobtracker.match.profile import Profile, build_profile
from jobtracker.normalize.cascade import normalize as real_normalize
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.runtime import pipeline, replay
from jobtracker.runtime.pipeline import ingest
from jobtracker.runtime.replay import UnknownStage, format_report, run_replay
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import get_posting, mark_favorite, update_resolution
from test_runtime_pipeline import _PROFILE_DATA

pytestmark = pytest.mark.db

_DESCRIPTIONS = [
    "We are hiring a graduate to join our desk. Visa sponsorship is available. Python and C++.",
    "Requires 5+ years of experience building low latency systems in C++. No sponsorship.",
    "Junior developer wanted, 1-2 years of experience. Python, SQL and Linux.",
    "Join our trading team. We offer a competitive salary of $150,000 - $180,000 per year.",
]


@pytest.fixture
def profile() -> Profile:
    return build_profile(_PROFILE_DATA)


@pytest.fixture(autouse=True)
def _company(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    store_conn.commit()


def _degrade_seniority(raw: RawPosting, **kwargs: object) -> Posting:
    """An older parser that never resolved seniority."""
    posting = real_normalize(raw, **kwargs)  # type: ignore[arg-type]
    return posting.model_copy(update={"seniority": Seniority.UNKNOWN, "min_years": None})


def _degrade_location(raw: RawPosting, **kwargs: object) -> Posting:
    """A parser that lost its city → country resolution."""
    posting = real_normalize(raw, **kwargs)  # type: ignore[arg-type]
    unresolved = tuple(
        Location(city=None, country=None, region=None, remote_mode=loc.remote_mode, raw=loc.raw)
        for loc in posting.locations
    )
    return posting.model_copy(update={"locations": unresolved})


def _degrade_both(raw: RawPosting, **kwargs: object) -> Posting:
    posting = _degrade_seniority(raw, **kwargs)
    unresolved = tuple(
        Location(city=None, country=None, region=None, remote_mode=loc.remote_mode, raw=loc.raw)
        for loc in posting.locations
    )
    return posting.model_copy(update={"locations": unresolved})


def _ingest_many(
    conn: sqlite3.Connection, n: int, taxonomy: Taxonomy, geo: GeoIndex, profile: Profile
) -> list[str]:
    ids = []
    for i in range(n):
        raw = RawPosting(
            source=Source.GREENHOUSE,
            company_slug="acme",
            source_job_id=f"job-{i}",
            url=f"https://example.com/{i}",
            # Distinct titles: identical ones would (rightly) be deduplicated into one posting.
            title_raw=f"{'Quantitative Developer' if i % 2 else 'Software Engineer'} Desk {i}",
            description_raw=_DESCRIPTIONS[i % len(_DESCRIPTIONS)] + f" Ref {i}.",
            location_raw="London, United Kingdom",
            department_raw=None,
            posted_at_raw="2026-01-02T00:00:00Z",
            payload=b"{}",
            fetched_at=datetime(2026, 1, 5, tzinfo=UTC),
            content_hash=f"hash-{i}",
        )
        result = ingest(conn, raw, taxonomy=taxonomy, geo=geo, profile=profile, hq_country="GB")
        assert result.posting_id is not None
        ids.append(result.posting_id)
    return ids


def _run(
    conn: sqlite3.Connection, taxonomy: Taxonomy, geo: GeoIndex, profile: Profile, **kw: object
):
    return run_replay(conn, taxonomy=taxonomy, geo=geo, profile=profile, **kw)  # type: ignore[arg-type]


@pytest.fixture
def old_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pipeline, "normalize", _degrade_seniority)


def test_a_dry_run_writes_nothing_and_shows_the_improvement(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    old_parser: None,
) -> None:
    _ingest_many(store_conn, 40, taxonomy, geo_index, profile)
    store_conn.commit()
    changes_before = store_conn.total_changes

    report = _run(store_conn, taxonomy, geo_index, profile)

    assert store_conn.total_changes == changes_before  # not a single write
    assert report.applied is False
    seniority = next(s for s in report.stages if s.stage == "seniority")
    assert seniority.before == 0.0  # the old parser resolved nothing
    assert seniority.after >= 0.5  # the graduate and junior descriptions now resolve
    assert seniority.delta_pts > 0 and not report.regressions
    assert report.changed_postings > 0
    assert "dry run" in format_report(report)


def test_apply_on_a_thousand_postings_keeps_identity_and_favorites(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    old_parser: None,
) -> None:
    ids = _ingest_many(store_conn, 1000, taxonomy, geo_index, profile)
    for posting_id in ids[::50]:
        mark_favorite(store_conn, posting_id, True)
    store_conn.commit()
    identity = {
        r["posting_id"]: (r["first_seen_at"], r["fingerprint"])
        for r in store_conn.execute("SELECT posting_id, first_seen_at, fingerprint FROM postings")
    }
    flags = store_conn.execute("SELECT * FROM user_flags ORDER BY posting_id").fetchall()
    assert len(flags) == 20

    report = _run(store_conn, taxonomy, geo_index, profile, apply=True)

    assert report.applied and report.total == 1000
    after = {
        r["posting_id"]: (r["first_seen_at"], r["fingerprint"])
        for r in store_conn.execute("SELECT posting_id, first_seen_at, fingerprint FROM postings")
    }
    assert after == identity  # posting_id, first_seen_at and the dedup fingerprint
    assert store_conn.execute("SELECT * FROM user_flags ORDER BY posting_id").fetchall() == flags
    resolved = store_conn.execute(
        "SELECT COUNT(*) AS n FROM postings WHERE seniority != 'unknown'"
    ).fetchone()["n"]
    assert resolved >= 500  # and the fields did change


def test_a_degraded_normalizer_is_flagged_as_a_regression_and_not_applied(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ingest_many(store_conn, 30, taxonomy, geo_index, profile)
    store_conn.commit()
    monkeypatch.setattr(replay, "normalize", _degrade_location)

    report = _run(store_conn, taxonomy, geo_index, profile)
    assert [r.stage for r in report.regressions] == ["location"]
    assert "REGRESSION" in format_report(report)

    refused = _run(store_conn, taxonomy, geo_index, profile, apply=True)
    assert refused.applied is False and refused.refused is not None
    unresolved = store_conn.execute(
        "SELECT COUNT(*) AS n FROM posting_locations WHERE country IS NULL"
    ).fetchone()["n"]
    assert unresolved == 0  # nothing was written

    forced = _run(store_conn, taxonomy, geo_index, profile, apply=True, allow_regression=True)
    assert forced.applied is True


def test_a_replay_targeted_at_one_stage_changes_only_that_stages_fields(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "normalize", _degrade_both)
    ids = _ingest_many(store_conn, 20, taxonomy, geo_index, profile)
    store_conn.commit()
    before = {i: get_posting(store_conn, i) for i in ids}

    report = _run(store_conn, taxonomy, geo_index, profile, stage="seniority", apply=True)

    assert [s.stage for s in report.stages] == ["seniority"]
    for posting_id in ids:
        old, new = before[posting_id], get_posting(store_conn, posting_id)
        assert old is not None and new is not None
        assert new.locations == old.locations  # location was also degraded, but not replayed
        assert new.tech == old.tech and new.title == old.title
    assert any(
        (
            b is not None
            and (p := get_posting(store_conn, i)) is not None
            and p.seniority != b.seniority
        )
        for i, b in before.items()
    )


def test_fields_settled_by_the_llm_survive_a_replay(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    old_parser: None,
) -> None:
    (posting_id,) = _ingest_many(store_conn, 1, taxonomy, geo_index, profile)
    posting = get_posting(store_conn, posting_id)
    assert posting is not None
    settled = posting.model_copy(
        update={"seniority": Seniority.MID, "role_family": RoleFamily.QUANT_RESEARCH,
                "resolver_stage": "llm"}
    )  # fmt: skip
    update_resolution(
        store_conn, settled, __import__("factories_store").make_verdict(posting_id=posting_id)
    )
    store_conn.commit()

    _run(store_conn, taxonomy, geo_index, profile, apply=True)

    after = get_posting(store_conn, posting_id)
    assert after is not None
    assert (after.seniority, after.role_family) == (Seniority.MID, RoleFamily.QUANT_RESEARCH)
    assert after.resolver_stage == "llm"


def test_an_inactive_posting_is_not_resurrected_by_a_replay(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    old_parser: None,
) -> None:
    (posting_id,) = _ingest_many(store_conn, 1, taxonomy, geo_index, profile)
    store_conn.execute("UPDATE postings SET is_active = 0 WHERE posting_id = ?", (posting_id,))
    store_conn.commit()
    _run(store_conn, taxonomy, geo_index, profile, apply=True)
    row = store_conn.execute("SELECT is_active FROM postings").fetchone()
    assert row["is_active"] == 0


def test_the_exact_raw_inputs_are_archived_and_used(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    (posting_id,) = _ingest_many(store_conn, 1, taxonomy, geo_index, profile)
    row = store_conn.execute(
        "SELECT location_raw, posted_at_raw FROM postings WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    assert (row["location_raw"], row["posted_at_raw"]) == (
        "London, United Kingdom",
        "2026-01-02T00:00:00Z",
    )
    # No parser change: replaying the same normalizer on the same inputs is a fixed point.
    report = _run(store_conn, taxonomy, geo_index, profile)
    assert report.changed_postings == 0 and not report.tier_net


def test_an_unknown_stage_is_refused(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    with pytest.raises(UnknownStage):
        _run(store_conn, taxonomy, geo_index, profile, stage="astrology")


def test_the_replay_module_cannot_collect() -> None:
    source = replay.__file__ and open(replay.__file__, encoding="utf-8").read()  # noqa: SIM115
    assert source is not None
    assert "httpx" not in source and "jobtracker.collect" not in source
