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
    "senior_only",
    "phd_required",
    "stale",
    "low_score",
)


def hard_reject(posting: Posting, *, profile: Profile) -> str | None:
    if _title_matches_any(posting.title, profile.titles.excluded):
        return "excluded_title"
    if posting.role_family == RoleFamily.OTHER:
        return "not_quant"
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


def _title_matches_any(title: str, keywords: tuple[str, ...]) -> bool:
    title_l = title.lower()
    return any(re.search(rf"\b{re.escape(kw)}\b", title_l) for kw in keywords)


def _is_senior_only(posting: Posting, *, profile: Profile) -> bool:
    if posting.min_years is not None and posting.min_years > profile.hard_rejects.min_years_above:
        return True
    return _title_matches_any(posting.title, profile.seniority.reject_keywords)


def _is_stale(posting: Posting, *, profile: Profile) -> bool:
    age_days = (utc_now() - reference_date(posting)).days
    return age_days > profile.hard_rejects.stale_after_days
