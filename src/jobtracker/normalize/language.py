"""Posting language and required languages — blueprint/02-REPOSITORY-TREE.md (normalize/).

`detect_language` is a light heuristic used to decide which language's
patterns the other stages should trust more, and for corpus/metrics
purposes — `Posting` itself only persists `languages_required`, the
candidate-facing requirement ("fluent French required"), not the ad's own
language.
"""

import re

from jobtracker.normalize.taxonomy import Taxonomy

_LANGUAGE_NAME_TO_ISO = {
    "english": "en",
    "anglais": "en",
    "french": "fr",
    "français": "fr",
    "francais": "fr",
    "german": "de",
    "allemand": "de",
    "deutsch": "de",
    "dutch": "nl",
    "néerlandais": "nl",
    "spanish": "es",
    "espagnol": "es",
    "italian": "it",
    "italien": "it",
    "mandarin": "zh",
    "chinese": "zh",
    "mandarin chinese": "zh",
    "cantonese": "zh",
    "japanese": "ja",
    "japonais": "ja",
}

_REQUIREMENT_RE = re.compile(
    r"(?:fluent(?:\s+in)?|native(?:\s+speaker\s+of)?|proficien(?:t|cy)(?:\s+in)?|"
    r"bilingu(?:al|e)(?:\s+in)?|courant\s+en)\s+([a-zàâéèêëîïôûüç ]+)",
    re.IGNORECASE,
)


def detect_language(text: str, *, taxonomy: Taxonomy) -> str:
    """Best-effort ISO-639-1 guess for the ad's own language; defaults to English.

    Markers are matched on word boundaries: a substring check would let
    English "candidate" satisfy the French marker "candidat".
    """
    text_l = text.lower()
    best_lang = "en"
    best_score = 0
    for lang, markers in taxonomy.language.markers.items():
        score = sum(1 for marker in markers if re.search(rf"\b{re.escape(marker)}\b", text_l))
        if score > best_score:
            best_score = score
            best_lang = lang
    return best_lang


def parse_languages_required(description: str, *, taxonomy: Taxonomy) -> frozenset[str]:
    """Never raises (invariant I1) — worst case is an empty set."""
    found: set[str] = set()
    for match in _REQUIREMENT_RE.finditer(description):
        phrase = match.group(1).lower()
        for name, iso in _LANGUAGE_NAME_TO_ISO.items():
            if name in phrase:
                found.add(iso)
    # "bilingual French and English" / "bilingue français/anglais": a second
    # language often follows a conjunction right after the first.
    for match in re.finditer(r"\band\b|\bet\b|/", description, re.IGNORECASE):
        window = description[max(0, match.start() - 5) : match.end() + 20].lower()
        for name, iso in _LANGUAGE_NAME_TO_ISO.items():
            if name in window and any(m2 in description.lower() for m2 in ("bilingu",)):
                found.add(iso)
    return frozenset(found)
