"""`is_ambiguous` — blueprint/wp/WP12-match-llm.md §3, §5."""

import pytest

from factories_store import make_posting, make_verdict
from jobtracker.core.enums import RemoteMode, RoleFamily, Seniority, Tier, VisaStatus
from jobtracker.core.models import Location
from jobtracker.match.prefilter import is_ambiguous
from jobtracker.match.profile import Profile, build_profile

pytestmark = pytest.mark.contract

_LONG_DESCRIPTION = "We are hiring. " * 20  # > 200 chars
_SHORT_DESCRIPTION = "We are hiring."


def _location(country: str) -> Location:
    return Location(
        city=None, country=country, region=None, remote_mode=RemoteMode.ONSITE, raw=None
    )


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
    return build_profile(_PROFILE_DATA, company_tiers={"prop_shop": 1, "regional_bank": 3})


def test_hard_reject_is_never_ambiguous(profile: Profile) -> None:
    posting = make_posting(seniority=Seniority.SENIOR)
    verdict = make_verdict(score=0, tier=Tier.REJECTED, rejection_reason="senior_only", reasons=())
    assert is_ambiguous(posting, verdict, profile=profile, description=_LONG_DESCRIPTION) is False


def test_low_score_rejection_is_never_ambiguous(profile: Profile) -> None:
    posting = make_posting()
    verdict = make_verdict(score=10, tier=Tier.REJECTED, rejection_reason="low_score")
    assert is_ambiguous(posting, verdict, profile=profile, description=_LONG_DESCRIPTION) is False


def test_short_description_is_never_ambiguous_even_when_seniority_is_unknown(
    profile: Profile,
) -> None:
    posting = make_posting(seniority=Seniority.UNKNOWN)
    verdict = make_verdict(score=50, tier=Tier.POSSIBLE)
    assert is_ambiguous(posting, verdict, profile=profile, description=_SHORT_DESCRIPTION) is False


def test_not_quant_at_a_rank1_company_is_ambiguous(profile: Profile) -> None:
    posting = make_posting(
        company_slug="prop_shop", role_family=RoleFamily.OTHER, title="Software Engineer"
    )
    verdict = make_verdict(score=0, tier=Tier.REJECTED, rejection_reason="not_quant")
    assert is_ambiguous(posting, verdict, profile=profile, description=_LONG_DESCRIPTION) is True


def test_not_quant_at_a_non_rank1_company_is_not_ambiguous(profile: Profile) -> None:
    posting = make_posting(
        company_slug="regional_bank", role_family=RoleFamily.OTHER, title="Software Engineer"
    )
    verdict = make_verdict(score=0, tier=Tier.REJECTED, rejection_reason="not_quant")
    assert is_ambiguous(posting, verdict, profile=profile, description=_LONG_DESCRIPTION) is False


def test_unknown_seniority_is_ambiguous(profile: Profile) -> None:
    posting = make_posting(seniority=Seniority.UNKNOWN, visa_sponsorship=VisaStatus.SPONSORS)
    verdict = make_verdict(score=50, tier=Tier.POSSIBLE)
    assert is_ambiguous(posting, verdict, profile=profile, description=_LONG_DESCRIPTION) is True


def test_unknown_visa_outside_the_eu_is_ambiguous(profile: Profile) -> None:
    posting = make_posting(
        seniority=Seniority.JUNIOR,
        visa_sponsorship=VisaStatus.UNKNOWN,
        locations=(_location("US"),),
    )
    verdict = make_verdict(score=50, tier=Tier.POSSIBLE)
    assert is_ambiguous(posting, verdict, profile=profile, description=_LONG_DESCRIPTION) is True


def test_unknown_visa_inside_the_eu_is_not_ambiguous(profile: Profile) -> None:
    posting = make_posting(
        seniority=Seniority.JUNIOR, visa_sponsorship=VisaStatus.UNKNOWN
    )  # default location is FR, inside the EU
    verdict = make_verdict(score=50, tier=Tier.POSSIBLE)
    assert is_ambiguous(posting, verdict, profile=profile, description=_LONG_DESCRIPTION) is False


def test_comfortably_strong_and_fully_resolved_is_not_ambiguous(profile: Profile) -> None:
    posting = make_posting(seniority=Seniority.JUNIOR, visa_sponsorship=VisaStatus.SPONSORS)
    verdict = make_verdict(score=95, tier=Tier.STRONG)
    assert is_ambiguous(posting, verdict, profile=profile, description=_LONG_DESCRIPTION) is False


def test_borderline_strong_score_is_still_ambiguous_if_visa_unknown_outside_eu(
    profile: Profile,
) -> None:
    posting = make_posting(
        seniority=Seniority.JUNIOR,
        visa_sponsorship=VisaStatus.UNKNOWN,
        locations=(_location("SG"),),
    )
    # Just over strong=70 — not the comfortable margin _is_confidently_resolved requires.
    verdict = make_verdict(score=72, tier=Tier.STRONG)
    assert is_ambiguous(posting, verdict, profile=profile, description=_LONG_DESCRIPTION) is True
