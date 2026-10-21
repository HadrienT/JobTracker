"""The countries an application's location names — blueprint/wp/WP21-applications.md §6.

The spreadsheet wrote places by hand and colour-coded the cell by country; the colour did not
survive the CSV export, the text did: "CH (Zurich)", "UK (London) -> SG", "USA (New York) NY",
"Singapore/HK", "Amsterdam / Chicago". Applications recorded from the feed carry the feed's
labels: "New York, US · Greenwich, US". Both are read here, in order of appearance:

1. an upper-case two-to-three-letter code ("CH", "UK", "USA", "HK"; a US state code is the US);
2. a country's name, or a city named in the sheet ("Amsterdam", "Zurich");
3. failing both, a city of the geo referential that exists in one country only — a homonym
   ("London": GB or CA) is never guessed.

Pure: free text in, ISO 3166-1 alpha-2 codes out.
"""

import re
import unicodedata

from jobtracker.core.geo import GeoIndex

_WORD = re.compile(r"[A-Za-z]+")

# Upper-case codes as the sheet and the feed write them.
_CODES = {
    "CH": "CH", "UK": "GB", "GB": "GB", "USA": "US", "US": "US", "CA": "CA", "DE": "DE",
    "FR": "FR", "NL": "NL", "SG": "SG", "HK": "HK", "CN": "CN", "JP": "JP", "AU": "AU",
    "IE": "IE", "ES": "ES", "IT": "IT", "LU": "LU", "AT": "AT", "BE": "BE", "PL": "PL",
    "AE": "AE", "IN": "IN", "KR": "KR", "VN": "VN", "SE": "SE", "DK": "DK", "NO": "NO",
    "FI": "FI", "PT": "PT", "IL": "US", "NY": "US", "NJ": "US", "CT": "US", "PA": "US",
    "FL": "US", "MA": "US", "TX": "US", "WA": "US",
}  # fmt: skip
# In a job title ("Quant Dev UK"), only codes no title word could be: never "IT", "IN", "NO"…
_TITLE_CODES = frozenset({"CH", "UK", "GB", "USA", "US", "SG", "HK", "NL", "NY"})
# "IL" is Illinois in this history ("USA (Chicago) IL"), not Israel; "CA" is Canada
# ("CA (Montreal)"), never California — the sheet always wrote the state after "USA (…)".

# Names, lower-case, accents stripped; multi-word names are matched as phrases.
_NAMES = {
    "switzerland": "CH", "suisse": "CH", "schweiz": "CH",
    "zurich": "CH", "geneva": "CH", "geneve": "CH", "zug": "CH", "basel": "CH",
    "lausanne": "CH", "rotkreuz": "CH", "baden": "CH", "kloten": "CH", "opfikon": "CH",
    "pratteln": "CH", "kaiseraugst": "CH", "fribourg": "CH", "winterthur": "CH",
    "luzern": "CH", "lucerne": "CH", "nyon": "CH", "bern": "CH",
    "united kingdom": "GB", "england": "GB", "london": "GB",
    "united states": "US", "new york": "US", "chicago": "US", "miami": "US", "boston": "US",
    "greenwich": "US", "dallas": "US", "jersey city": "US", "bala cynwyd": "US",
    "downers grove": "US", "austin": "US", "san francisco": "US",
    "canada": "CA", "montreal": "CA", "toronto": "CA",
    "netherlands": "NL", "amsterdam": "NL",
    "germany": "DE", "munich": "DE", "frankfurt": "DE", "berlin": "DE",
    "france": "FR", "paris": "FR",
    "singapore": "SG", "sinpagore": "SG",
    "hong kong": "HK",
    "china": "CN", "shanghai": "CN", "beijing": "CN",
    "japan": "JP", "tokyo": "JP",
    "australia": "AU", "sydney": "AU",
    "ireland": "IE", "dublin": "IE",
    "vietnam": "VN", "hanoi": "VN",
}  # fmt: skip


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _unique_city_country(word: str, geo: GeoIndex) -> str | None:
    canonical = geo.alias_to_city.get(word)
    entries = geo.by_city.get(canonical, ()) if canonical else ()
    countries = {entry.country for entry in entries}
    return countries.pop() if len(countries) == 1 else None


def countries_in(
    text: str | None, *, geo: GeoIndex | None = None, title: bool = False
) -> tuple[str, ...]:
    """The countries `text` names, in order of appearance, each once. `title`: the text is a
    job title, not a place — only unmistakable codes and names count, no referential lookup."""
    if not text:
        return ()
    codes = _TITLE_CODES if title else _CODES.keys()
    found: list[tuple[int, str]] = []
    for match in _WORD.finditer(text):
        word = match.group()
        if word.isupper() and word in codes:
            found.append((match.start(), _CODES[word]))
    folded = _fold(text)
    padded = f" {' '.join(_WORD.findall(folded))} "
    words = padded.split()
    for name, country in _NAMES.items():
        position = padded.find(f" {name} ")
        if position != -1:
            found.append((folded.find(name.split()[0]), country))
    if not found and geo is not None and not title:
        for word in words:
            unique = _unique_city_country(word, geo)
            if unique is not None:
                found.append((folded.find(word), unique))
    ordered = [country for _, country in sorted(found, key=lambda item: item[0])]
    return tuple(dict.fromkeys(ordered))


def application_countries(
    location: str | None, title: str | None, *, geo: GeoIndex | None = None
) -> tuple[str, ...]:
    """An application's countries: from its location, else from its title ("Quant Dev SG")."""
    return countries_in(location, geo=geo) or countries_in(title, title=True)
