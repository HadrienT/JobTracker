"""Visa sponsorship status — blueprint/00-PRIMER.md §2 (P4), blueprint/10-PROFILE-TARGET.md §4.

Three states, never two (interdit n°4): silence is `UNKNOWN`, not `NO`. `NO`
is checked before `SPONSORS` on purpose — "we are unable to provide
sponsorship" contains the word "sponsorship" and must not fall through to a
naive positive match on that word alone (the double-negation trap this stage
exists for). A disguised restriction ("Remote (US only)", "must be based in
the EU") is read as `NO` too: it says the same thing without the word "visa".
"""

import re

from jobtracker.core.enums import VisaStatus
from jobtracker.normalize.taxonomy import Taxonomy


def _first_match(description: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return None


def parse_visa(description: str, *, taxonomy: Taxonomy) -> tuple[VisaStatus, str | None]:
    """Never raises (invariant I1) — worst case is `(UNKNOWN, None)`."""
    rules = taxonomy.visa

    no_evidence = _first_match(description, rules.no_phrases)
    if no_evidence is not None:
        return VisaStatus.NO, no_evidence

    restriction_evidence = _first_match(description, rules.restriction_phrases)
    if restriction_evidence is not None:
        return VisaStatus.NO, restriction_evidence

    sponsors_evidence = _first_match(description, rules.sponsors_phrases)
    if sponsors_evidence is not None:
        return VisaStatus.SPONSORS, sponsors_evidence

    return VisaStatus.UNKNOWN, None
