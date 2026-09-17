"""Tech stack extraction — blueprint/wp/WP03-normalize.md §3.

Aliases come from `configs/taxonomy.yaml`. Single-letter/ambiguous names
("R", "Go", "C") are the one place this stage carries its own grammar rather
than a plain alias list: "R" must not match "HR", and "Go" must not match
"go live" — they only count delimited by word boundaries *and* sitting next
to another item in a tech list (a comma, slash or "and" on at least one
side), never as a bare word floating in a sentence.
"""

import re

from jobtracker.normalize.taxonomy import Taxonomy

_LIST_NEIGHBOR = r"(?:,|/|\band\b|\bor\b)"


def _alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(alias)
    if re.fullmatch(r"[a-z0-9]+", alias):
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


def _ambiguous_pattern(token: str) -> re.Pattern[str]:
    escaped = re.escape(token)
    return re.compile(
        rf"(?:{_LIST_NEIGHBOR}\s*\b{escaped}\b|\b{escaped}\b\s*{_LIST_NEIGHBOR})",
        re.IGNORECASE,
    )


def parse_tech(description: str, *, taxonomy: Taxonomy) -> frozenset[str]:
    """Never raises (invariant I1) — worst case is an empty set."""
    rules = taxonomy.tech
    found: set[str] = set()

    for canonical, aliases in rules.aliases.items():
        if any(_alias_pattern(alias).search(description) for alias in aliases):
            found.add(canonical)

    for canonical, token in rules.ambiguous_single_token.items():
        if _ambiguous_pattern(token).search(description):
            found.add(canonical)

    return frozenset(found)
