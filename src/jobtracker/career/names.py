"""Matching the user's free-hand names — blueprint/wp/WP21-applications.md §3.

The same employer is written "QRT", "QubeRT" and "Qube Research & Technologies"; the same job
"Quant Dev NY" in a folder name and "Quant Dev" + "USA (New York) NY" in the sheet. These
helpers turn either side into comparable keys and token sets. Pure functions.
"""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

_PARENTHESIZED = re.compile(r"\([^)]*\)")
_NON_ALNUM = re.compile(r"[^a-z0-9+]+")
# Legal-form and filler words that never tell two employers apart.
_COMPANY_NOISE = frozenset(
    {
        "ag", "sa", "llc", "lp", "ltd", "inc", "plc", "co", "and", "the",
        "group", "management", "capital", "technologies", "technology", "technologie", "tech",
        "research", "securities", "partners", "asset",
    }
)  # fmt: skip
# The same words glued to the name ("ManGroup", "HeadlandsTech"), longest first.
_GLUED_NOISE = sorted((w for w in _COMPANY_NOISE if len(w) >= 4), key=len, reverse=True)
# Words that say who sent the application, not what the job is.
_AGENCY_WORDS = frozenset({"recruter", "recruiter", "recruiting", "agency"})
# Words of a job title → their canonical token. Applied to folder names and sheet titles alike.
_TITLE_SYNONYMS = {
    "quantitative": "quant",
    "developer": "dev",
    "developper": "dev",
    "development": "dev",
    "software": "sw",
    "swe": "sw eng",
    "engineer": "eng",
    "engineering": "eng",
    "cpp": "c++",
    "researcher": "research",
    "analyst": "analyst",
    "qr": "quant research",
    "qd": "quant dev",
    "ml": "ml",
    "mle": "ml eng",
    "graduate": "grad",
    "junior": "junior",
}
_TITLE_NOISE = frozenset({"a", "the", "of", "and", "i", "ii", "iii", "1", "2", "3", "new", "-"})
# Place words → (canonical place, region), so "NY" in a folder meets "USA (New York) NY" and
# "Asia" in a folder meets "HK / Singapore". A region word alone has no place.
_PLACES: dict[str, tuple[str | None, str]] = {
    "ny": ("new_york", "us"), "nyc": ("new_york", "us"), "new york": ("new_york", "us"),
    "chicago": ("chicago", "us"), "il": ("chicago", "us"), "miami": ("miami", "us"),
    "greenwich": ("greenwich", "us"), "boston": ("boston", "us"), "dallas": ("dallas", "us"),
    "usa": (None, "us"), "us": (None, "us"),
    "sg": ("singapore", "asia"), "singapore": ("singapore", "asia"),
    "sinpagore": ("singapore", "asia"),
    "hk": ("hong_kong", "asia"), "hong kong": ("hong_kong", "asia"),
    "shanghai": ("shanghai", "asia"), "asia": (None, "asia"),
    "uk": ("london", "europe"), "london": ("london", "europe"),
    "amsterdam": ("amsterdam", "europe"), "nl": ("amsterdam", "europe"),
    "paris": ("paris", "europe"), "munich": ("munich", "europe"),
    "zurich": ("zurich", "europe"), "zh": ("zurich", "europe"),
    "geneva": ("geneva", "europe"), "zug": ("zug", "europe"), "basel": ("basel", "europe"),
    "lausanne": ("lausanne", "europe"), "eu": (None, "europe"), "europe": (None, "europe"),
    "montreal": ("montreal", "canada"),
}  # fmt: skip
_PLACE_WORDS = frozenset(word for key in _PLACES for word in key.split())


def fold(text: str) -> str:
    """Lowercase, accents stripped."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def company_key(name: str, aliases: Mapping[str, str] | None = None) -> str:
    """A comparison key for an employer name; `aliases` maps a key to its canonical key."""
    text = _PARENTHESIZED.sub(" ", fold(name)).replace("&", " ")
    words = [w for w in _NON_ALNUM.split(text) if w and w not in _COMPANY_NOISE]
    key = "".join(words) or "".join(_NON_ALNUM.split(fold(name)))
    for suffix in _GLUED_NOISE:
        if key.endswith(suffix) and len(key) - len(suffix) >= 3:
            key = key[: -len(suffix)]
            break
    return (aliases or {}).get(key, key)


def alias_map(config: Mapping[str, list[str]]) -> dict[str, str]:
    """`configs/company_aliases.yaml` (canonical → variants) as variant → canonical."""
    mapping = {canonical: canonical for canonical in config}
    for canonical, variants in config.items():
        for variant in variants:
            mapping[variant] = canonical
    return mapping


def title_tokens(text: str) -> frozenset[str]:
    """Canonical tokens of a job title, places removed."""
    words = _NON_ALNUM.split(fold(text))
    tokens: set[str] = set()
    for word in words:
        if not word or word in _TITLE_NOISE or word in _PLACE_WORDS:
            continue
        tokens.update(_TITLE_SYNONYMS.get(word, word).split())
    return frozenset(tokens)


@dataclass(frozen=True)
class Places:
    specific: frozenset[str]  # cities
    regions: frozenset[str]  # us, europe, asia, canada


def places(text: str) -> Places:
    """The places named in free text: a folder name or a sheet location."""
    folded = " " + " ".join(_NON_ALNUM.split(fold(text))) + " "
    found = [spot for word, spot in _PLACES.items() if f" {word} " in folded]
    return Places(
        specific=frozenset(place for place, _ in found if place),
        regions=frozenset(region for _, region in found),
    )


def place_agreement(left: Places, right: Places) -> int | None:
    """+3 same cities, +2 overlapping, +1 same region only, negative when they disagree;
    None when either side names no place."""
    if left.specific and right.specific:
        if left.specific == right.specific:
            return 3
        if left.specific & right.specific:
            return 2
        return -1 if left.regions & right.regions else -3
    if left.regions and right.regions:
        return 1 if left.regions & right.regions else -3
    return None


def name_leftover(longer: str, shorter: str) -> str:
    """The words of employer name `longer` that `shorter` lacks, as a title hint:
    "Google Gemini" minus "Google" → "Gemini"; "Aquatic Capital (Quant)" → "Quant"."""
    drop = set(_NON_ALNUM.split(fold(shorter))) | _COMPANY_NOISE | _AGENCY_WORDS
    return " ".join(w for w in _NON_ALNUM.split(fold(longer)) if w and w not in drop)
