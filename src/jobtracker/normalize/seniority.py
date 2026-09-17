"""Seniority and years of experience — blueprint/10-PROFILE-TARGET.md §3.

Resolution order, strict: explicit years in the description, then graduate
program markers, then title-level markers, then `UNKNOWN`. When the
description gives explicit years, it wins outright — a "Junior Developer"
title next to "5+ years of experience" in the body is `SENIOR`, not
`JUNIOR`: the title is recruiting marketing, the description is what the
recruiter will actually filter on.

Programme/intern/level markers are read from the **title only**. The
description is free text written for a human, not for this parser: the same
company boilerplate that says "see our campus postings" as a *disclaimer*
("this role is for experienced hires — students, look elsewhere") sits right
next to an FPGA Engineer posting and an actual campus-hire one alike, so
scanning the whole description for "campus"/"intern" produces exactly the
kind of false positive the title never would.
"""

import re

from jobtracker.core.enums import Seniority
from jobtracker.core.logging import get_logger
from jobtracker.normalize.taxonomy import SeniorityRules, Taxonomy

_logger = get_logger(__name__)

_INTERN_RE = re.compile(r"\bintern(?:ship)?\b|\bstagiaire\b|working student", re.IGNORECASE)
_CAMPUS_RE = re.compile(r"\bcampus\b", re.IGNORECASE)
_GRADUATE_TITLE_RE = re.compile(r"\bgraduate\b", re.IGNORECASE)
_COMPANY_HISTORY_DISQUALIFIERS = (
    "history of",
    "founded",
    "since 19",
    "since 20",
    "in innovation",
    "en innovation",
    "nous avons",
    "we have a",
)


def _years_to_seniority(years: int) -> Seniority:
    if years <= 2:
        return Seniority.JUNIOR
    if years <= 4:
        return Seniority.MID
    return Seniority.SENIOR


def _find_years(text: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if not match.groups():
                continue
            context = text[max(0, match.start() - 40) : match.end() + 20]
            if any(marker in context for marker in _COMPANY_HISTORY_DISQUALIFIERS):
                continue  # "25+ year track record" is the company's age, not a requirement
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                continue
    return None


def _title_category(title_l: str, rules: SeniorityRules) -> Seniority | None:
    if _INTERN_RE.search(title_l):
        return Seniority.INTERN
    if (
        _CAMPUS_RE.search(title_l)
        or _GRADUATE_TITLE_RE.search(title_l)
        or any(kw in title_l for kw in rules.program_keywords)
    ):
        return Seniority.GRADUATE
    for level in (Seniority.LEAD, Seniority.SENIOR, Seniority.JUNIOR):
        if any(kw in title_l for kw in rules.title_keywords.get(level.value, ())):
            return level
    return None


def parse_seniority(
    title: str, description: str, *, taxonomy: Taxonomy
) -> tuple[Seniority, int | None]:
    """Never raises (invariant I1) — worst case is `(UNKNOWN, None)`."""
    rules = taxonomy.seniority
    title_l = f" {title.lower()} "
    description_l = f" {description.lower()} "

    years = _find_years(description_l, rules.years_patterns)
    if years is not None:
        derived = _years_to_seniority(years)
        title_hint = _title_category(title_l, rules)
        if title_hint is None or title_hint == derived:
            return derived, years
        if title_hint in (Seniority.GRADUATE, Seniority.INTERN) and derived == Seniority.JUNIOR:
            # Not a real contradiction: "New Grad ... 0-2 years" agree with
            # each other, and the title names the more specific level.
            return title_hint, years
        _logger.info(
            "seniority_contradiction",
            title=title,
            title_hint=title_hint.value,
            description_years=years,
            resolved=derived.value,
        )
        return derived, years

    title_hint = _title_category(title_l, rules)
    if title_hint is not None:
        return title_hint, None

    return Seniority.UNKNOWN, None
