"""`tools/llm_load.py` — blueprint/wp/WP12-match-llm.md §6: produces the funnel on real data."""

import sqlite3
from datetime import UTC, datetime

import pytest
from tools.llm_load import compute_funnel

from jobtracker.core.enums import (
    RemoteMode,
    RoleFamily,
    Seniority,
    Source,
    Tier,
    VisaStatus,
)
from jobtracker.core.models import Compensation, Location, MatchVerdict, Posting, SourceRun
from jobtracker.match.profile import Profile, build_profile
from jobtracker.store.postings import upsert_posting
from jobtracker.store.runs import record_run
from jobtracker.store.search import index_description

pytestmark = pytest.mark.db

_NOW = datetime(2026, 1, 1, tzinfo=UTC)

_PROFILE_DATA = {
    "version": 1,
    "titles": {"strong": [], "possible": [], "excluded": []},
    "seniority": {"accept_if_years_max": 3, "reject": []},
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
    "freshness": {"window_days": 7, "stale_penalty_fraction": 0.5},
    "llm": {
        "min_description_chars": 200,
        "high_confidence_margin": 20,
        "min_confidence": 0.6,
        "max_description_chars": 6000,
    },
    "review": {
        "version": 1,
        "override_confidence": 0.8,
        "evidence_min_chars": 6,
        "max_locations": 8,
        "max_per_collect": 300,
        "max_output_tokens": 1200,
        "max_description_chars": 12000,
        "salary_bounds": {
            "year": [10000, 10000000],
            "month": [500, 500000],
            "day": [20, 20000],
            "hour": [5, 5000],
        },
        "currencies": ["USD", "EUR", "GBP", "CHF", "SGD", "HKD"],
        "currency_symbols": {"$": ["USD", "SGD", "HKD"], "£": ["GBP"], "€": ["EUR"]},
    },
}


@pytest.fixture
def profile() -> Profile:
    return build_profile(_PROFILE_DATA, company_tiers={"acme": 3})


def _seed_company(conn: sqlite3.Connection, *, slug: str, priority: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO companies "
        "(company_slug, company_name, source, token, sector, hq_country, priority, enabled) "
        "VALUES (?, ?, 'greenhouse', ?, 'prop_trading', 'US', ?, 1)",
        (slug, slug, slug, priority),
    )


def _posting(*, posting_id: str, company_slug: str, **overrides: object) -> Posting:
    base: dict[str, object] = {
        "posting_id": posting_id,
        "fingerprint": f"fp-{posting_id}",
        "source": Source.GREENHOUSE,
        "company_slug": company_slug,
        "source_job_id": posting_id,
        "url": f"https://example.com/{posting_id}",
        "title": "Quant Developer",
        "title_raw": "Quant Developer",
        "role_family": RoleFamily.QUANT_DEV,
        "seniority": Seniority.JUNIOR,
        "min_years": None,
        "phd_required": False,
        "locations": (
            Location(
                city="Paris", country="FR", region=None, remote_mode=RemoteMode.ONSITE, raw="Paris"
            ),
        ),
        "compensation": Compensation(
            amount_min=None,
            amount_max=None,
            currency=None,
            period=None,
            bonus_mentioned=False,
            equity_mentioned=False,
            raw=None,
        ),
        "visa_sponsorship": VisaStatus.SPONSORS,
        "visa_evidence": None,
        "tech": frozenset({"python"}),
        "languages_required": frozenset(),
        "posted_at": _NOW,
        "first_seen_at": _NOW,
        "last_seen_at": _NOW,
        "closes_at": None,
        "content_hash": f"hash-{posting_id}",
        "resolver_stage": "rules",
        "normalize_version": 1,
    }
    base.update(overrides)
    return Posting(**base)  # type: ignore[arg-type]


def test_funnel_counts_real_rows_across_every_stage(
    store_conn: sqlite3.Connection, profile: Profile
) -> None:
    _seed_company(store_conn, slug="acme", priority=3)

    rejected = _posting(posting_id="p-rejected", company_slug="acme")
    upsert_posting(
        store_conn,
        rejected,
        MatchVerdict(
            posting_id=rejected.posting_id,
            score=0,
            tier=Tier.REJECTED,
            reasons=(),
            rejection_reason="senior_only",
            profile_version=1,
            scored_at=_NOW,
        ),
    )
    index_description(store_conn, rejected.posting_id, "short")

    ambiguous = _posting(posting_id="p-ambiguous", company_slug="acme", seniority=Seniority.UNKNOWN)
    upsert_posting(
        store_conn,
        ambiguous,
        MatchVerdict(
            posting_id=ambiguous.posting_id,
            score=50,
            tier=Tier.POSSIBLE,
            reasons=(),
            rejection_reason=None,
            profile_version=1,
            scored_at=_NOW,
        ),
    )
    index_description(store_conn, ambiguous.posting_id, "A long enough description. " * 20)

    record_run(
        store_conn,
        SourceRun(
            run_id="r1",
            source=Source.GREENHOUSE,
            company_slug="acme",
            started_at=_NOW,
            ended_at=_NOW,
            fetched=10,
            new=2,
            updated=0,
            aliased=0,
            rejected=0,
            requests_made=5,
            status="ok",
            error_kind=None,
        ),
    )
    store_conn.commit()

    stages = compute_funnel(store_conn, days=3650, profile=profile)
    by_label = {stage.label: stage.count for stage in stages}

    assert by_label["new postings fetched"] == 10
    assert by_label["after content-hash cache"] == 2
    assert by_label["after not_quant / excluded_title"] == 2
    assert by_label["after senior_only / phd_required"] == 1  # the senior_only posting is gone
    assert by_label["after full deterministic resolution"] == 1  # only the non-rejected one
    assert by_label["after the prefilter"] == 1  # unknown seniority, long description: ambiguous
