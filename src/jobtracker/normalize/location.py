"""Free text → `tuple[Location, ...]` — blueprint/wp/WP03-normalize.md §3.

Delegates city resolution (including the homonym disambiguation via
`hq_country`) to `core.geo.resolve_location`; this module's own job is
splitting a compound location string into segments and reading the
remote/hybrid/region/country-restriction qualifier out of it — the part
`core.geo` deliberately leaves at `RemoteMode.UNKNOWN` for this stage to
refine.
"""

import re

from jobtracker.core.enums import RemoteMode
from jobtracker.core.geo import GeoIndex, resolve_location
from jobtracker.core.models import Location

_HYBRID_RE = re.compile(r"\bhybrid\b", re.IGNORECASE)
_REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)
_ONSITE_RE = re.compile(r"\bon[- ]?site\b", re.IGNORECASE)
_PLACEHOLDER_RE = re.compile(
    r"^\s*(?:multiple locations?|various locations?|see job description|tbd|to be determined)\s*$",
    re.IGNORECASE,
)
_PAREN_QUALIFIER_RE = re.compile(r"\(([^)]*)\)")
_DASH_QUALIFIER_RE = re.compile(r"(?:remote|hybrid)\s*[-–:]\s*([a-z ]+)$", re.IGNORECASE)
_SPLIT_RE = re.compile(r"\s*/\s*|\s*;\s*|\s+or\s+", re.IGNORECASE)

_REGION_WORDS = {"emea": "emea", "amer": "amer", "americas": "amer", "apac": "apac"}
_COUNTRY_RESTRICTION_WORDS = {
    "us": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "united states": "US",
    "uk": "GB",
    "u.k.": "GB",
    "united kingdom": "GB",
    "canada": "CA",
}
# A bare country name with no city at all ("Brazil", "Remote — Germany") is a
# real, if coarse, location: worth resolving to (city=None, country=ISO)
# rather than inventing nothing whatsoever.
_BARE_COUNTRY_NAMES = {
    "united states": "US",
    "usa": "US",
    "u.s.": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "france": "FR",
    "germany": "DE",
    "netherlands": "NL",
    "switzerland": "CH",
    "ireland": "IE",
    "spain": "ES",
    "italy": "IT",
    "brazil": "BR",
    "canada": "CA",
    "singapore": "SG",
    "hong kong": "HK",
    "japan": "JP",
    "australia": "AU",
    "india": "IN",
    "china": "CN",
}


def _resolve_bare_country(text: str) -> Location | None:
    iso = _BARE_COUNTRY_NAMES.get(text.strip().lower())
    if iso is None:
        return None
    return Location(city=None, country=iso, region=None, remote_mode=RemoteMode.UNKNOWN, raw=text)


def _find_region(qualifier: str) -> str | None:
    for word, region in _REGION_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", qualifier):
            return region
    return None


def _find_country(qualifier: str) -> str | None:
    for word, country in _COUNTRY_RESTRICTION_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", qualifier):
            return country
    return None


def _empty_location(text: str | None, remote_mode: RemoteMode = RemoteMode.UNKNOWN) -> Location:
    return Location(city=None, country=None, region=None, remote_mode=remote_mode, raw=text)


def parse_location(
    text: str | None, *, geo: GeoIndex, hq_country: str | None = None
) -> tuple[Location, ...]:
    """Never raises (invariant I1); an unparseable string yields one empty `Location`."""
    if text is None or not text.strip():
        return (_empty_location(text),)
    if _PLACEHOLDER_RE.match(text.strip()):
        return (_empty_location(text),)

    remote_mode = RemoteMode.UNKNOWN
    if _HYBRID_RE.search(text):
        remote_mode = RemoteMode.HYBRID
    elif _REMOTE_RE.search(text):
        remote_mode = RemoteMode.REMOTE
    elif _ONSITE_RE.search(text):
        remote_mode = RemoteMode.ONSITE

    region: str | None = None
    country_restriction: str | None = None
    working = text

    paren_match = _PAREN_QUALIFIER_RE.search(text)
    if paren_match:
        qualifier = paren_match.group(1).lower()
        region = _find_region(qualifier)
        country_restriction = _find_country(qualifier)
        working = _PAREN_QUALIFIER_RE.sub(" ", working)

    dash_match = _DASH_QUALIFIER_RE.search(text)
    if dash_match:
        qualifier = dash_match.group(1).lower()
        region = region or _find_region(qualifier)
        country_restriction = country_restriction or _find_country(qualifier)
        working = _DASH_QUALIFIER_RE.sub(" ", working)

    if remote_mode in (RemoteMode.REMOTE, RemoteMode.HYBRID, RemoteMode.ONSITE):
        working = _REMOTE_RE.sub(" ", working)
        working = _HYBRID_RE.sub(" ", working)
        working = _ONSITE_RE.sub(" ", working)

    working = working.strip(" \t-–—,()")

    if not working:
        # A pure qualifier mention ("Remote - EMEA", "Remote (US only)"): the
        # restriction is the whole point, nothing is invented for the city.
        return (
            Location(
                city=None,
                country=country_restriction,
                region=region,
                remote_mode=remote_mode,
                raw=text,
            ),
        )

    segments = [s.strip() for s in _SPLIT_RE.split(working) if s.strip()]
    if not segments:
        return (_empty_location(text, remote_mode),)

    locations = []
    seen: set[tuple[str | None, str | None]] = set()
    for segment in segments:
        for resolved in _resolve_segment(segment, geo, hq_country):
            merged_country = resolved.country or country_restriction
            key = (resolved.city, merged_country)
            if key in seen:
                continue
            seen.add(key)
            locations.append(
                resolved.model_copy(
                    update={"remote_mode": remote_mode, "raw": text, "country": merged_country}
                )
            )
    if not locations:
        return (_empty_location(text, remote_mode),)
    return tuple(locations)


def _resolve_segment(segment: str, geo: GeoIndex, hq_country: str | None) -> list[Location]:
    """Resolve one comma-free-form segment, possibly into more than one city.

    "New York, NY, United States" is one city under three names (an alias and
    a country qualifier); "London, New York" is two different cities. Both
    use a bare comma, so the only way to tell them apart is to try each part
    and see how many *distinct* real cities come back.
    """
    whole = resolve_location(segment, geo, hq_country=hq_country)
    if whole.city is not None:
        return [whole]
    bare_country = _resolve_bare_country(segment)
    if bare_country is not None:
        return [bare_country]
    if "," not in segment:
        return [whole]
    distinct: dict[tuple[str | None, str | None], Location] = {}
    for part in segment.split(","):
        candidate = resolve_location(part.strip(), geo, hq_country=hq_country)
        if candidate.city is not None:
            distinct[(candidate.city, candidate.country)] = candidate
    return list(distinct.values()) or [whole]
