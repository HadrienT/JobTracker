"""City → (country, region) referential, loaded from configs/geo.yaml.

The homonymy traps (Cambridge, London, Birmingham, Saint Petersburg — see
blueprint/wp/WP01-core.md §2) are resolved using the hiring company's
`hq_country` as the first clue. The choice made is always logged. A place
that cannot be resolved yields `city=None`, never an invention.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jobtracker.core.config import load_yaml
from jobtracker.core.enums import RemoteMode
from jobtracker.core.errors import ConfigError
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Location

_logger = get_logger(__name__)


@dataclass(frozen=True)
class CityEntry:
    city: str
    country: str
    region: str
    lat: float  # WGS84 degrees, city centre — where the map pins the city
    lon: float


@dataclass(frozen=True)
class ResolvedCity:
    city: str
    country: str
    region: str


@dataclass(frozen=True)
class GeoIndex:
    """Pre-built lookup tables — not a wire DTO, so a plain dataclass suffices."""

    alias_to_city: Mapping[str, str]
    by_city: Mapping[str, tuple[CityEntry, ...]]
    ambiguous_defaults: Mapping[str, str]


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def build_geo_index(data: Mapping[str, Any], *, source: Path | str | None = None) -> GeoIndex:
    """Build a `GeoIndex` from already-loaded YAML data — pure, no I/O."""
    where = f" ({source})" if source is not None else ""
    raw_cities = data.get("cities")
    if not isinstance(raw_cities, list):
        raise ConfigError(f"geo config{where}: 'cities' must be a list")

    alias_to_city: dict[str, str] = {}
    by_city: dict[str, list[CityEntry]] = {}
    for i, entry in enumerate(raw_cities):
        if not isinstance(entry, dict):
            raise ConfigError(f"geo config{where}: cities[{i}] must be a mapping")
        try:
            city = str(entry["city"])
            country = str(entry["country"]).upper()
            region = str(entry["region"])
            lat = float(entry["lat"])
            lon = float(entry["lon"])
        except KeyError as exc:
            raise ConfigError(f"geo config{where}: cities[{i}] is missing field {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"geo config{where}: cities[{i}] lat/lon must be numbers") from exc
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            raise ConfigError(f"geo config{where}: cities[{i}] ({city}) lat/lon out of range")
        normalized = _normalize(city)
        by_city.setdefault(normalized, []).append(
            CityEntry(city=city, country=country, region=region, lat=lat, lon=lon)
        )
        alias_to_city[normalized] = normalized
        for alias in entry.get("aliases", []):
            alias_to_city[_normalize(str(alias))] = normalized

    raw_ambiguous = data.get("ambiguous", {})
    if not isinstance(raw_ambiguous, dict):
        raise ConfigError(f"geo config{where}: 'ambiguous' must be a mapping")
    ambiguous_defaults: dict[str, str] = {}
    for name, options in raw_ambiguous.items():
        default_country = (
            (options or {}).get("default_country") if isinstance(options, dict) else None
        )
        if default_country:
            ambiguous_defaults[_normalize(str(name))] = str(default_country).upper()

    return GeoIndex(
        alias_to_city=alias_to_city,
        by_city={k: tuple(v) for k, v in by_city.items()},
        ambiguous_defaults=ambiguous_defaults,
    )


def load_geo_index(path: Path) -> GeoIndex:
    """Load and build the `GeoIndex` from `configs/geo.yaml` (or an equivalent)."""
    return build_geo_index(load_yaml(path), source=path)


def city_coordinates(index: GeoIndex, city: str, country: str) -> tuple[float, float] | None:
    """`(lat, lon)` of a resolved city, or None when the referential does not know it."""
    for entry in index.by_city.get(_normalize(city), ()):
        if entry.country == country.upper():
            return entry.lat, entry.lon
    return None


def resolve_city(index: GeoIndex, raw_city: str, *, hq_country: str | None) -> ResolvedCity | None:
    """Resolve free text to a city, disambiguating homonyms via `hq_country`."""
    normalized = _normalize(raw_city)
    canonical = index.alias_to_city.get(normalized)
    if canonical is None:
        return None
    candidates = index.by_city.get(canonical, ())
    if not candidates:
        return None
    if len(candidates) == 1:
        entry = candidates[0]
        return ResolvedCity(city=entry.city, country=entry.country, region=entry.region)

    chosen: CityEntry | None = None
    reason = "unresolved"
    if hq_country is not None:
        matches = [c for c in candidates if c.country == hq_country.upper()]
        if matches:
            chosen, reason = matches[0], "hq_country_match"
    if chosen is None:
        default_country = index.ambiguous_defaults.get(canonical)
        if default_country is not None:
            matches = [c for c in candidates if c.country == default_country]
            if matches:
                chosen, reason = matches[0], "default_country"

    if chosen is None:
        _logger.warning(
            "geo_ambiguous_unresolved",
            raw_city=raw_city,
            hq_country=hq_country,
            candidate_countries=[c.country for c in candidates],
        )
        return None

    _logger.info(
        "geo_city_disambiguated",
        raw_city=raw_city,
        hq_country=hq_country,
        resolved_country=chosen.country,
        reason=reason,
    )
    return ResolvedCity(city=chosen.city, country=chosen.country, region=chosen.region)


def resolve_location(raw: str | None, index: GeoIndex, *, hq_country: str | None) -> Location:
    """Build a `Location` skeleton from free text; `remote_mode` stays `UNKNOWN`.

    Detecting "Hybrid" / "Remote" wording is `normalize.location`'s job
    (WP03), which owns the full text and refines this result.
    """
    if raw is None or not raw.strip():
        return Location(
            city=None, country=None, region=None, remote_mode=RemoteMode.UNKNOWN, raw=raw
        )
    resolved = resolve_city(index, raw, hq_country=hq_country)
    if resolved is None:
        return Location(
            city=None, country=None, region=None, remote_mode=RemoteMode.UNKNOWN, raw=raw
        )
    return Location(
        city=resolved.city,
        country=resolved.country,
        region=resolved.region,
        remote_mode=RemoteMode.UNKNOWN,
        raw=raw,
    )
