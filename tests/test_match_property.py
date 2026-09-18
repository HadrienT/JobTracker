"""Invariant I3 by construction — blueprint/wp/WP12-match-llm.md §3, §5.

Rather than trying to synthesize a real "would an LLM change this" oracle,
these tests check the two properties `is_ambiguous` is defined by: it never
spends a call on a verdict that is already final, and it never silently
skips one of the specific uncertainty signals the prefilter table names.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from factories_store import make_posting, make_verdict
from jobtracker.core.enums import Seniority, Tier, VisaStatus
from jobtracker.match.prefilter import is_ambiguous
from jobtracker.match.profile import Profile, build_profile

pytestmark = pytest.mark.property

_LONG_DESCRIPTION = "We are hiring for this role. " * 20

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
}

_REJECTION_REASONS = st.sampled_from(
    ["excluded_title", "not_quant", "senior_only", "phd_required", "stale", "low_score"]
)


@pytest.fixture(scope="module")
def profile() -> Profile:
    # No company is rank 1: isolates the "already rejected" property from the
    # not_quant/rank-1 carve-out, which test_match_prefilter.py covers directly.
    return build_profile(_PROFILE_DATA, company_tiers={})


@given(rejection_reason=_REJECTION_REASONS)
def test_never_ambiguous_once_finally_rejected(rejection_reason: str, profile: Profile) -> None:
    posting = make_posting()
    verdict = make_verdict(score=0, tier=Tier.REJECTED, rejection_reason=rejection_reason)
    assert is_ambiguous(posting, verdict, profile=profile, description=_LONG_DESCRIPTION) is False


@given(score=st.integers(min_value=25, max_value=100))
def test_always_ambiguous_when_seniority_unknown_and_not_rejected(
    score: int, profile: Profile
) -> None:
    posting = make_posting(seniority=Seniority.UNKNOWN, visa_sponsorship=VisaStatus.SPONSORS)
    tier = Tier.STRONG if score >= 70 else Tier.POSSIBLE if score >= 45 else Tier.STRETCH
    verdict = make_verdict(score=score, tier=tier, rejection_reason=None)
    assert is_ambiguous(posting, verdict, profile=profile, description=_LONG_DESCRIPTION) is True


@given(description=st.text(max_size=199))
def test_never_ambiguous_under_the_minimum_description_length(
    description: str, profile: Profile
) -> None:
    posting = make_posting(seniority=Seniority.UNKNOWN)
    verdict = make_verdict(score=50, tier=Tier.POSSIBLE)
    assert is_ambiguous(posting, verdict, profile=profile, description=description) is False
