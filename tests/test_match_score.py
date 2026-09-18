"""`evaluate` contract tests — blueprint/wp/WP05-match.md §6, invariant I5."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from factories_store import make_posting
from jobtracker.core.clock import freeze
from jobtracker.core.enums import RoleFamily, Seniority, Tier, VisaStatus
from jobtracker.match.profile import Profile, build_profile, load_profile
from jobtracker.match.score import evaluate

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parent.parent
_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

_PROFILE_DATA = {
    "version": 1,
    "titles": {
        "strong": ["quant developer"],
        "possible": ["software engineer"],
        "excluded": ["recruiter"],
    },
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
    return build_profile(_PROFILE_DATA, company_tiers={"tier1_shop": 1, "tier3_vendor": 3})


def test_rejected_tier_always_carries_a_reason(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(role_family=RoleFamily.OTHER)
        verdict = evaluate(posting, profile=profile)
    assert verdict.tier == Tier.REJECTED
    assert verdict.rejection_reason == "not_quant"
    assert verdict.reasons == ()


def test_non_rejected_tier_never_carries_a_reason(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(
            title="Quant Developer",
            role_family=RoleFamily.QUANT_DEV,
            company_slug="tier1_shop",
        )
        verdict = evaluate(posting, profile=profile)
    assert verdict.tier != Tier.REJECTED
    assert verdict.rejection_reason is None


def test_low_score_that_passed_hard_rejects_is_still_rejected_with_a_reason(
    profile: Profile,
) -> None:
    with freeze(_EPOCH):
        posting = make_posting(
            title="Risk Analyst",
            role_family=RoleFamily.RISK,
            seniority=Seniority.UNKNOWN,
            min_years=None,
            tech=frozenset(),
            visa_sponsorship=VisaStatus.UNKNOWN,
        )
        verdict = evaluate(posting, profile=profile)
    assert verdict.tier == Tier.REJECTED
    assert verdict.rejection_reason == "low_score"


def test_visa_no_applies_the_configured_penalty_with_evidence(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(
            title="Quant Developer",
            role_family=RoleFamily.QUANT_DEV,
            visa_sponsorship=VisaStatus.NO,
            visa_evidence="US citizens only.",
        )
        verdict = evaluate(posting, profile=profile)
    visa_reasons = [r for r in verdict.reasons if r.code == "visa_no"]
    assert len(visa_reasons) == 1
    assert visa_reasons[0].delta == -25
    assert visa_reasons[0].evidence == "US citizens only."


def test_visa_unknown_applies_no_penalty(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(
            title="Quant Developer",
            role_family=RoleFamily.QUANT_DEV,
            visa_sponsorship=VisaStatus.UNKNOWN,
        )
        verdict = evaluate(posting, profile=profile)
    assert all(r.code not in ("visa_no", "visa_sponsors") for r in verdict.reasons)


@pytest.mark.parametrize(
    ("weights", "expected_bound"),
    [
        ({"title_strong": 1000}, 100),
        ({"visa_no": -1000}, 0),
    ],
)
def test_score_is_bounded_0_100(weights: dict[str, int], expected_bound: int) -> None:
    extreme_data = {**_PROFILE_DATA, "weights": {**_PROFILE_DATA["weights"], **weights}}
    extreme_profile = build_profile(extreme_data)
    with freeze(_EPOCH):
        posting = make_posting(
            title="Quant Developer",
            role_family=RoleFamily.QUANT_DEV,
            visa_sponsorship=VisaStatus.NO,
            visa_evidence="no sponsorship",
        )
        verdict = evaluate(posting, profile=extreme_profile)
    assert 0 <= verdict.score <= 100
    assert verdict.score == expected_bound


def test_two_evaluations_of_the_same_posting_are_identical(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(title="Quant Developer", role_family=RoleFamily.QUANT_DEV)
        first = evaluate(posting, profile=profile)
        second = evaluate(posting, profile=profile)
    assert first.model_dump() == second.model_dump()


def test_profile_version_is_propagated(profile: Profile) -> None:
    with freeze(_EPOCH):
        posting = make_posting(title="Quant Developer", role_family=RoleFamily.QUANT_DEV)
        verdict = evaluate(posting, profile=profile)
    assert verdict.profile_version == profile.version


@pytest.mark.parametrize(
    "posting_kwargs",
    [
        {"role_family": RoleFamily.OTHER},
        {"title": "Staff Engineer", "role_family": RoleFamily.SWE_PLATFORM},
        {"phd_required": True, "role_family": RoleFamily.QUANT_RESEARCH},
        {
            "title": "Quant Developer",
            "role_family": RoleFamily.QUANT_DEV,
            "company_slug": "tier1_shop",
        },
        {
            "title": "Risk Analyst",
            "role_family": RoleFamily.RISK,
            "seniority": Seniority.UNKNOWN,
            "min_years": None,
            "tech": frozenset(),
            "visa_sponsorship": VisaStatus.UNKNOWN,
        },
    ],
)
def test_invariant_i5_tier_rejected_iff_rejection_reason(
    profile: Profile, posting_kwargs: dict[str, object]
) -> None:
    with freeze(_EPOCH):
        posting = make_posting(**posting_kwargs)
        verdict = evaluate(posting, profile=profile)
    assert (verdict.tier == Tier.REJECTED) == (verdict.rejection_reason is not None)


def test_tier1_prop_shop_software_engineer_is_possible_or_better() -> None:
    real_profile = load_profile(
        REPO_ROOT / "configs" / "profile.yaml", company_tiers={"tier1_shop": 1}
    )
    with freeze(_EPOCH):
        posting = make_posting(
            title="Software Engineer",
            role_family=RoleFamily.SWE_PLATFORM,
            company_slug="tier1_shop",
            seniority=Seniority.JUNIOR,
            tech=frozenset({"cpp", "python"}),
        )
        verdict = evaluate(posting, profile=real_profile)
    assert verdict.tier in (Tier.POSSIBLE, Tier.STRONG)


def test_tier3_vendor_software_engineer_scores_notably_lower() -> None:
    real_profile = load_profile(
        REPO_ROOT / "configs" / "profile.yaml", company_tiers={"tier1_shop": 1, "tier3_vendor": 3}
    )
    with freeze(_EPOCH):
        base = {
            "title": "Software Engineer",
            "role_family": RoleFamily.SWE_PLATFORM,
            "seniority": Seniority.JUNIOR,
            "tech": frozenset({"cpp", "python"}),
        }
        tier1_verdict = evaluate(
            make_posting(**base, company_slug="tier1_shop"), profile=real_profile
        )
        tier3_verdict = evaluate(
            make_posting(**base, company_slug="tier3_vendor"), profile=real_profile
        )
    assert tier3_verdict.score < tier1_verdict.score


def test_changing_a_weight_without_bumping_version_is_caught() -> None:
    # blueprint/wp/WP05-match.md §6: this is the hygiene test the DoD requires.
    # It fails the moment configs/profile.yaml's weights change under the same
    # `version` — the fix is either to revert the weight or to bump `version`
    # and update this frozen snapshot in the same commit.
    known_weights_by_version = {
        1: {
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
    }
    real_profile = load_profile(REPO_ROOT / "configs" / "profile.yaml")
    known = known_weights_by_version.get(real_profile.version)
    assert known is not None, (
        f"no frozen snapshot recorded for profile version {real_profile.version}"
    )
    assert dict(real_profile.weights) == known
