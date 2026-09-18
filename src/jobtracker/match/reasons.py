"""The score's contributions — blueprint/10-PROFILE-TARGET.md §6.

Each function below inspects one signal and returns at most one `Reason`,
carrying the `evidence` that triggered it when a natural excerpt exists.
`evaluate` (in `score.py`) only ever sums what these return — no weight is
read anywhere else, and none of them is ever a literal in this file.
"""

import re
from collections.abc import Iterator

from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Seniority, VisaStatus
from jobtracker.core.models import Posting, Reason
from jobtracker.match.profile import Profile
from jobtracker.match.rules import reference_date

_NICHE_TECH = frozenset({"kdb", "ocaml", "rust", "cuda", "fpga"})


def contributions(posting: Posting, *, profile: Profile) -> tuple[Reason, ...]:
    return tuple(_iter_contributions(posting, profile=profile))


def _iter_contributions(posting: Posting, *, profile: Profile) -> Iterator[Reason]:
    title_reason = _title(posting, profile=profile)
    if title_reason is not None:
        yield title_reason
    sector = _sector_tier1(posting, profile=profile)
    if sector is not None:
        yield sector
    seniority = _seniority_match(posting, profile=profile)
    if seniority is not None:
        yield seniority
    graduate = _graduate_programme(posting, profile=profile)
    if graduate is not None:
        yield graduate
    yield from _tech(posting, profile=profile)
    visa = _visa(posting, profile=profile)
    if visa is not None:
        yield visa
    freshness = _freshness(posting, profile=profile)
    if freshness is not None:
        yield freshness
    salary = _salary_disclosed(posting, profile=profile)
    if salary is not None:
        yield salary
    stale = _stale_penalty(posting, profile=profile)
    if stale is not None:
        yield stale


def _matches_any(title: str, keywords: tuple[str, ...]) -> str | None:
    title_l = title.lower()
    for keyword in keywords:
        if re.search(rf"\b{re.escape(keyword)}\b", title_l):
            return keyword
    return None


def _title(posting: Posting, *, profile: Profile) -> Reason | None:
    if _matches_any(posting.title, profile.titles.strong) is not None:
        return Reason(
            code="title_strong", delta=profile.weights["title_strong"], evidence=posting.title
        )
    if _matches_any(posting.title, profile.titles.possible) is not None:
        return Reason(
            code="title_possible", delta=profile.weights["title_possible"], evidence=posting.title
        )
    return None


def _sector_tier1(posting: Posting, *, profile: Profile) -> Reason | None:
    if profile.company_tiers.get(posting.company_slug) == 1:
        return Reason(code="sector_tier1", delta=profile.weights["sector_tier1"], evidence=None)
    return None


def _seniority_match(posting: Posting, *, profile: Profile) -> Reason | None:
    target_seniority = posting.seniority in (Seniority.GRADUATE, Seniority.JUNIOR, Seniority.INTERN)
    target_years = (
        posting.min_years is not None and posting.min_years <= profile.seniority.accept_if_years_max
    )
    if target_seniority or target_years:
        evidence = f"min_years={posting.min_years}" if posting.min_years is not None else None
        return Reason(
            code="seniority_match", delta=profile.weights["seniority_match"], evidence=evidence
        )
    return None


def _graduate_programme(posting: Posting, *, profile: Profile) -> Reason | None:
    if posting.seniority == Seniority.GRADUATE:
        return Reason(
            code="graduate_programme", delta=profile.weights["graduate_programme"], evidence=None
        )
    return None


def _tech(posting: Posting, *, profile: Profile) -> Iterator[Reason]:
    if "cpp" in posting.tech:
        yield Reason(code="tech_cpp", delta=profile.weights["tech_cpp"], evidence="cpp")
    if "python" in posting.tech:
        yield Reason(code="tech_python", delta=profile.weights["tech_python"], evidence="python")
    niche_hit = posting.tech & _NICHE_TECH
    if niche_hit:
        yield Reason(
            code="tech_niche",
            delta=profile.weights["tech_niche"],
            evidence=", ".join(sorted(niche_hit)),
        )


def _visa(posting: Posting, *, profile: Profile) -> Reason | None:
    if posting.visa_sponsorship == VisaStatus.SPONSORS:
        return Reason(
            code="visa_sponsors",
            delta=profile.weights["visa_sponsors"],
            evidence=posting.visa_evidence,
        )
    if posting.visa_sponsorship == VisaStatus.NO:
        return Reason(
            code="visa_no", delta=profile.weights["visa_no"], evidence=posting.visa_evidence
        )
    return None


def _freshness(posting: Posting, *, profile: Profile) -> Reason | None:
    age_days = (utc_now() - reference_date(posting)).days
    if age_days <= profile.freshness.window_days:
        return Reason(
            code="freshness_7d",
            delta=profile.weights["freshness_7d"],
            evidence=f"age_days={age_days}",
        )
    return None


def _salary_disclosed(posting: Posting, *, profile: Profile) -> Reason | None:
    if posting.compensation.amount_min is not None:
        return Reason(
            code="salary_disclosed",
            delta=profile.weights["salary_disclosed"],
            evidence=posting.compensation.raw,
        )
    return None


def _stale_penalty(posting: Posting, *, profile: Profile) -> Reason | None:
    age_days = (utc_now() - reference_date(posting)).days
    stale_from = profile.hard_rejects.stale_after_days * profile.freshness.stale_penalty_fraction
    if age_days > stale_from:
        return Reason(
            code="stale_penalty",
            delta=profile.weights["stale_penalty"],
            evidence=f"age_days={age_days}",
        )
    return None
