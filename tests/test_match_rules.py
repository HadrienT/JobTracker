"""Hard reject contract tests — blueprint/wp/WP05-match.md §3, §6."""

from datetime import UTC, datetime

import pytest

from factories_store import make_posting
from jobtracker.core.clock import freeze
from jobtracker.core.enums import RoleFamily, Seniority
from jobtracker.match.profile import Profile, build_profile
from jobtracker.match.rules import hard_reject

# Every test here runs against the shared frozen instant (tests/conftest.py).
pytestmark = pytest.mark.usefixtures("frozen_clock")

pytestmark = pytest.mark.contract

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

_PROFILE_DATA = {
    "version": 1,
    "titles": {
        "strong": ["quant developer"],
        "possible": ["software engineer"],
        "excluded": ["coordinator", "recruiter"],
    },
    "seniority": {
        "accept_if_years_max": 3,
        "reject": ["senior", "lead", "principal", "staff", "vp"],
    },
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
    return build_profile(_PROFILE_DATA)


def test_not_quant_when_role_family_is_other(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(role_family=RoleFamily.OTHER, title="Executive Assistant")
        assert hard_reject(posting, profile=profile) == "not_quant"


def test_swe_platform_is_never_rejected_as_not_quant(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(role_family=RoleFamily.SWE_PLATFORM, title="Software Engineer")
        assert hard_reject(posting, profile=profile) is None


def test_staff_engineer_is_senior_only(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(title="Staff Engineer", role_family=RoleFamily.SWE_PLATFORM)
        assert hard_reject(posting, profile=profile) == "senior_only"


def test_staffing_coordinator_is_excluded_title_not_senior_only(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(title="Staffing Coordinator", role_family=RoleFamily.SWE_PLATFORM)
        assert hard_reject(posting, profile=profile) == "excluded_title"


def test_phd_preferred_is_not_a_rejection(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(phd_required=False, role_family=RoleFamily.QUANT_RESEARCH)
        assert hard_reject(posting, profile=profile) is None


def test_phd_required_is_a_rejection(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(phd_required=True, role_family=RoleFamily.QUANT_RESEARCH)
        assert hard_reject(posting, profile=profile) == "phd_required"


def test_min_years_above_threshold_is_senior_only(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(
            min_years=5, title="Quant Developer", role_family=RoleFamily.QUANT_DEV
        )
        assert hard_reject(posting, profile=profile) == "senior_only"


def test_min_years_at_threshold_is_not_rejected(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(
            min_years=4, title="Quant Developer", role_family=RoleFamily.QUANT_DEV
        )
        assert hard_reject(posting, profile=profile) is None


def test_unknown_seniority_and_no_min_years_is_receivable(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(
            seniority=Seniority.UNKNOWN,
            min_years=None,
            title="Quant Developer",
            role_family=RoleFamily.QUANT_DEV,
        )
        assert hard_reject(posting, profile=profile) is None


def test_stale_posting_is_rejected() -> None:
    profile = build_profile(_PROFILE_DATA)
    with freeze(_EPOCH):
        posting = make_posting(
            role_family=RoleFamily.QUANT_DEV,
            title="Quant Developer",
            posted_at=_EPOCH,
            first_seen_at=_EPOCH,
        )
    with freeze(datetime(2026, 4, 1, tzinfo=UTC)):  # 90 days later
        assert hard_reject(posting, profile=profile) == "stale"


def test_fresh_posting_is_not_stale() -> None:
    profile = build_profile(_PROFILE_DATA)
    posting = make_posting(
        role_family=RoleFamily.QUANT_DEV,
        title="Quant Developer",
        posted_at=_EPOCH,
        first_seen_at=_EPOCH,
    )
    with freeze(datetime(2026, 1, 10, tzinfo=UTC)):  # 9 days later
        assert hard_reject(posting, profile=profile) is None
