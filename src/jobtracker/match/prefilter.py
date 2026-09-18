"""The free prefilter — blueprint/wp/WP12-match-llm.md §3.

`is_ambiguous` decides whether a posting's LLM call would be worth the GPU
contention it costs. It only ever screens a posting **out** when it is
certain the call could not change the verdict — invariant I3, zero false
negatives (blueprint/wp/WP12-match-llm.md §3): a spurious LLM call costs a
few seconds of GPU, but a posting wrongly screened out vanishes without a
trace and nobody will ever notice its absence. When in doubt, this module
lets the posting through.

`Posting` carries no description text (it lives only in `posting_search_text`,
blueprint/04-DATA-MODEL.md §3, read back through `store.search.get_description`)
so the caller passes it in separately — the one deliberate deviation from the
bare `is_ambiguous(posting, verdict, *, profile)` sketch in
blueprint/03-INTERFACES.md §3.3.
"""

from jobtracker.core.enums import Seniority, Tier, VisaStatus
from jobtracker.core.models import MatchVerdict, Posting
from jobtracker.match.profile import Profile

# Below this many characters, there is nothing in the description an LLM
# could read that the regexes upstream would have missed.
_MIN_DESCRIPTION_CHARS = 200

# "très au-dessus du seuil strong" — comfortably clear of the tier boundary,
# not just a couple of points over it.
_HIGH_CONFIDENCE_MARGIN = 20

# EU-27: a candidate holding EU citizenship needs no visa sponsorship inside
# this set, which is why `visa_sponsorship == UNKNOWN` is far less consequential
# here than it is for a US, UK, Swiss or APAC posting (P4).
_EU_COUNTRIES = frozenset(
    {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE",
        "GR", "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT",
        "RO", "SK", "SI", "ES", "SE",
    }
)  # fmt: skip


def is_ambiguous(
    posting: Posting, verdict: MatchVerdict, *, profile: Profile, description: str
) -> bool:
    """`True` only when a human — or the LLM standing in for one — would need
    to actually read the posting to confirm or overturn the deterministic verdict.
    """
    if verdict.rejection_reason is not None and not _is_reviewable_not_quant(
        posting, verdict, profile=profile
    ):
        return False  # every other hard reject / low_score is final (§3)

    if len(description) < _MIN_DESCRIPTION_CHARS:
        return False  # nothing to read, whatever else is uncertain

    if verdict.rejection_reason == "not_quant":
        # Confirmed above: rank-1 company, description long enough to be worth reading.
        return True

    if _is_confidently_resolved(posting, verdict, profile=profile):
        return False

    if posting.seniority == Seniority.UNKNOWN:
        return True
    return posting.visa_sponsorship == VisaStatus.UNKNOWN and not _has_eu_location(posting)


def _is_reviewable_not_quant(posting: Posting, verdict: MatchVerdict, *, profile: Profile) -> bool:
    """`not_quant` is normalize's classifier defaulting to "other" — worth a second
    look only at a company the registry already knows hires quants (rank 1); at
    any other company "other" is simply "other".
    """
    return (
        verdict.rejection_reason == "not_quant"
        and profile.company_tiers.get(posting.company_slug) == 1
    )


def _is_confidently_resolved(posting: Posting, verdict: MatchVerdict, *, profile: Profile) -> bool:
    if verdict.tier == Tier.REJECTED:
        return False
    fully_resolved = (
        posting.seniority != Seniority.UNKNOWN and posting.visa_sponsorship != VisaStatus.UNKNOWN
    )
    return fully_resolved and verdict.score >= profile.tiers.strong + _HIGH_CONFIDENCE_MARGIN


def _has_eu_location(posting: Posting) -> bool:
    return any(location.country in _EU_COUNTRIES for location in posting.locations)
