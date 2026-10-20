"""Hard rejects — blueprint/wp/WP05-match.md §3, blueprint/10-PROFILE-TARGET.md §3/§6.

These short-circuit `evaluate`: no score is computed for a posting a hard
reject already excludes. Order matters — an explicit `excluded_title` is a
human override and wins over everything else, including a role family that
would otherwise read as `not_quant` too.
"""

import re
from datetime import datetime

from jobtracker.core.clock import utc_now
from jobtracker.core.enums import RoleFamily
from jobtracker.core.models import Posting
from jobtracker.match.profile import Profile

# Every identifier `evaluate` can persist as a `rejection_reason` (the five hard rejects
# here, plus `low_score` from score.py). They are stored, shown in the UI and aggregated in
# the weekly report: renaming one silently splits its history, so tests/test_discipline.py
# pins this set.
REJECTION_REASONS = (
    "excluded_title",
    "not_quant",
    "off_topic",
    "senior_only",
    "phd_required",
    "stale",
    "low_score",
)


def hard_reject(posting: Posting, *, profile: Profile) -> str | None:
    if _title_matches_any(posting.title, profile.titles.excluded):
        return "excluded_title"
    if posting.role_family == RoleFamily.OTHER:
        # The quant feed's own word for it, which the LLM lane may overturn (match.prefilter);
        # a track, which has a topic, files it with the rest of what it is not about.
        return "not_quant" if profile.topic is None else "off_topic"
    # Final, never sent to the LLM: an excluded employer, or a track's subject missing.
    if profile.company_sectors.get(posting.company_slug) in profile.scope.exclude_sectors:
        return "off_topic"
    if not on_topic(posting, profile=profile):
        return "off_topic"
    if _is_senior_only(posting, profile=profile):
        return "senior_only"
    if profile.hard_rejects.phd_required and posting.phd_required:
        return "phd_required"
    if _is_stale(posting, profile=profile):
        return "stale"
    return None


def reference_date(posting: Posting) -> datetime:
    """The date staleness and freshness are measured from — blueprint/09-CONVENTIONS.md §3.

    `posted_at` is trusted only when normalize already kept it (it is
    discarded there whenever it would postdate `first_seen_at`), so here it
    is simply "use it if present, `first_seen_at` otherwise".
    """
    return posting.posted_at or posting.first_seen_at


def in_scope(posting: Posting, *, profile: Profile) -> bool:
    """Whether `profile` scores this posting at all: one of its locations is in the scope.

    Out of scope is not a rejection — a Paris posting is simply not part of a Swiss track,
    the same way a Swiss one is part of the quant feed without belonging to it any more.
    """
    countries = profile.scope.countries
    return not countries or any(loc.country in countries for loc in posting.locations)


def on_topic(posting: Posting, *, profile: Profile) -> bool:
    """A track's subject: a topic keyword in the title, or a topic tag in the stack."""
    topic = profile.topic
    if topic is None:
        return True
    if posting.tech & topic.tech:
        return True
    return title_keyword(posting.title, topic.titles) is not None


def title_keyword(title: str, keywords: tuple[str, ...]) -> str | None:
    """The first keyword found in `title` as a whole word, `None` if none is.

    Word edges are "not a letter or digit", not `\b`: "c++" ends on a non-word character,
    where `\b` never matches — the keyword would silently never apply.
    """
    title_l = title.lower()
    for keyword in keywords:
        if re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", title_l):
            return keyword
    return None


def _title_matches_any(title: str, keywords: tuple[str, ...]) -> bool:
    return title_keyword(title, keywords) is not None


def _is_senior_only(posting: Posting, *, profile: Profile) -> bool:
    if posting.min_years is not None and posting.min_years > profile.hard_rejects.min_years_above:
        return True
    return _title_matches_any(posting.title, profile.seniority.reject_keywords)


def _is_stale(posting: Posting, *, profile: Profile) -> bool:
    age_days = (utc_now() - reference_date(posting)).days
    return age_days > profile.hard_rejects.stale_after_days
