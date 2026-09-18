"""`evaluate` — blueprint/wp/WP05-match.md §2, blueprint/03-INTERFACES.md §3.3.

The order is fixed: a hard reject short-circuits before any contribution is
computed (no score for a posting that is out of scope), then contributions
are summed, clamped to [0, 100], and mapped to a tier. A score below the
`stretch` floor is *also* a rejection — `low_score` — because invariant I5
requires every `tier == REJECTED` verdict to carry a `rejection_reason`, and
a hard reject's five motifs don't cover "passed every rule but scored low".
"""

from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Tier
from jobtracker.core.models import MatchVerdict, Posting
from jobtracker.match.profile import Profile
from jobtracker.match.reasons import contributions
from jobtracker.match.rules import hard_reject


def evaluate(posting: Posting, *, profile: Profile) -> MatchVerdict:
    reason = hard_reject(posting, profile=profile)
    if reason is not None:
        return MatchVerdict(
            posting_id=posting.posting_id,
            score=0,
            tier=Tier.REJECTED,
            reasons=(),
            rejection_reason=reason,
            profile_version=profile.version,
            scored_at=utc_now(),
        )

    reasons = contributions(posting, profile=profile)
    score = max(0, min(100, sum(r.delta for r in reasons)))
    tier = _tier_for(score, profile=profile)
    return MatchVerdict(
        posting_id=posting.posting_id,
        score=score,
        tier=tier,
        reasons=reasons,
        rejection_reason=None if tier != Tier.REJECTED else "low_score",
        profile_version=profile.version,
        scored_at=utc_now(),
    )


def _tier_for(score: int, *, profile: Profile) -> Tier:
    if score >= profile.tiers.strong:
        return Tier.STRONG
    if score >= profile.tiers.possible:
        return Tier.POSSIBLE
    if score >= profile.tiers.stretch:
        return Tier.STRETCH
    return Tier.REJECTED
