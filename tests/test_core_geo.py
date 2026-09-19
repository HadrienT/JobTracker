from pathlib import Path

import pytest

from jobtracker.core.enums import RemoteMode
from jobtracker.core.errors import ConfigError
from jobtracker.core.geo import (
    GeoIndex,
    build_geo_index,
    city_coordinates,
    load_geo_index,
    resolve_city,
    resolve_location,
)


def test_geo_yaml_covers_at_least_40_cities(geo_config_path: Path) -> None:
    index = load_geo_index(geo_config_path)
    assert len(index.by_city) >= 40


@pytest.mark.parametrize(
    ("city", "hq_country", "expected_country"),
    [
        ("Cambridge", "US", "US"),
        ("Cambridge", "GB", "GB"),
        ("Birmingham", "US", "US"),
        ("Birmingham", "GB", "GB"),
        ("Saint Petersburg", "RU", "RU"),
        ("Saint Petersburg", "US", "US"),
        ("London", "GB", "GB"),
        ("London", "CA", "CA"),
    ],
)
def test_homonym_traps_resolve_via_hq_country(
    geo_config_path: Path, city: str, hq_country: str, expected_country: str
) -> None:
    index = load_geo_index(geo_config_path)
    resolved = resolve_city(index, city, hq_country=hq_country)
    assert resolved is not None
    assert resolved.country == expected_country


def test_cambridge_resolutions_are_distinct_for_different_hq_countries(
    geo_config_path: Path,
) -> None:
    index = load_geo_index(geo_config_path)
    us_resolution = resolve_city(index, "Cambridge", hq_country="US")
    gb_resolution = resolve_city(index, "Cambridge", hq_country="GB")
    assert us_resolution is not None
    assert gb_resolution is not None
    assert us_resolution.country != gb_resolution.country


def test_london_defaults_to_gb_without_hq_hint(geo_config_path: Path) -> None:
    index = load_geo_index(geo_config_path)
    resolved = resolve_city(index, "London", hq_country=None)
    assert resolved is not None
    assert resolved.country == "GB"


def test_ambiguous_city_without_default_and_without_hq_hint_is_unresolved(
    geo_config_path: Path,
) -> None:
    index = load_geo_index(geo_config_path)
    assert resolve_city(index, "Cambridge", hq_country=None) is None


def test_unknown_city_is_unresolved() -> None:
    index = build_geo_index(
        {
            "cities": [
                {"city": "Paris", "country": "FR", "region": "emea", "lat": 48.86, "lon": 2.35}
            ]
        }
    )
    assert resolve_city(index, "Nowheresville", hq_country=None) is None


def test_resolve_location_unknown_place_preserves_raw_text() -> None:
    index = build_geo_index(
        {
            "cities": [
                {"city": "Paris", "country": "FR", "region": "emea", "lat": 48.86, "lon": 2.35}
            ]
        }
    )
    location = resolve_location("Nowheresville, Wonderland", index, hq_country=None)
    assert location.city is None
    assert location.country is None
    assert location.raw == "Nowheresville, Wonderland"
    assert location.remote_mode == RemoteMode.UNKNOWN


def test_resolve_location_none_input_preserves_raw_none() -> None:
    index = build_geo_index({"cities": []})
    location = resolve_location(None, index, hq_country=None)
    assert location.city is None
    assert location.raw is None


def test_alias_resolves_to_canonical_city() -> None:
    index = build_geo_index(
        {
            "cities": [
                {
                    "city": "New York",
                    "country": "US",
                    "region": "amer",
                    "lat": 40.71,
                    "lon": -74.0,
                    "aliases": ["NYC"],
                }
            ]
        }
    )
    resolved = resolve_city(index, "nyc", hq_country=None)
    assert resolved is not None
    assert resolved.city == "New York"


def test_build_geo_index_rejects_missing_field() -> None:
    with pytest.raises(ConfigError):
        build_geo_index({"cities": [{"city": "Paris", "country": "FR"}]})


def test_build_geo_index_rejects_non_list_cities() -> None:
    with pytest.raises(ConfigError):
        build_geo_index({"cities": "not-a-list"})


def test_missing_coordinates_are_a_config_error() -> None:
    with pytest.raises(ConfigError, match="lat"):
        build_geo_index({"cities": [{"city": "Paris", "country": "FR", "region": "emea"}]})


@pytest.mark.parametrize(("lat", "lon"), [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_out_of_range_coordinates_are_a_config_error(lat: float, lon: float) -> None:
    entry = {"city": "Paris", "country": "FR", "region": "emea", "lat": lat, "lon": lon}
    with pytest.raises(ConfigError, match="out of range"):
        build_geo_index({"cities": [entry]})


def test_non_numeric_coordinates_are_a_config_error() -> None:
    entry = {"city": "Paris", "country": "FR", "region": "emea", "lat": "north", "lon": 2.35}
    with pytest.raises(ConfigError, match="numbers"):
        build_geo_index({"cities": [entry]})


def test_city_coordinates_tell_homonyms_apart(geo_index: GeoIndex) -> None:
    london_gb = city_coordinates(geo_index, "London", "GB")
    london_ca = city_coordinates(geo_index, "London", "CA")
    assert london_gb is not None
    assert london_ca is not None
    assert london_gb != london_ca
    assert city_coordinates(geo_index, "london", "gb") == london_gb  # case-insensitive
    assert city_coordinates(geo_index, "London", "FR") is None
    assert city_coordinates(geo_index, "Atlantis", "GB") is None


# Rough bounding boxes (lat_min, lat_max, lon_min, lon_max): not a geography test, a guard
# against the typo that matters — a flipped sign that would pin Chicago in the Pacific.
_COUNTRY_BOXES = {
    "GB": (49.8, 60.9, -8.7, 1.8), "CA": (41.6, 83.2, -141.0, -52.0),
    "US": (24.4, 49.5, -125.0, -66.9), "RU": (41.0, 82.0, 19.0, 180.0),
    "FR": (41.3, 51.2, -5.2, 9.7), "NL": (50.7, 53.6, 3.3, 7.3),
    "DE": (47.2, 55.1, 5.8, 15.1), "CH": (45.8, 47.9, 5.9, 10.6),
    "IE": (51.3, 55.5, -10.7, -5.9), "LU": (49.4, 50.2, 5.7, 6.6),
    "ES": (35.9, 43.9, -9.4, 4.4), "IT": (36.6, 47.1, 6.6, 18.6),
    "SE": (55.3, 69.1, 10.9, 24.2), "DK": (54.5, 57.8, 8.0, 15.2),
    "PL": (49.0, 54.9, 14.1, 24.2), "CZ": (48.5, 51.1, 12.0, 18.9),
    "AT": (46.3, 49.1, 9.5, 17.2), "BE": (49.5, 51.6, 2.5, 6.5),
    "AE": (22.6, 26.1, 51.5, 56.4), "IL": (29.4, 33.4, 34.2, 35.9),
    "KY": (19.2, 19.8, -81.5, -79.7), "HK": (22.1, 22.6, 113.8, 114.5),
    "SG": (1.1, 1.5, 103.6, 104.1), "JP": (24.0, 46.0, 122.0, 146.0),
    "CN": (18.0, 54.0, 73.0, 135.0), "AU": (-44.0, -10.0, 112.0, 154.0),
    "IN": (6.5, 35.7, 68.0, 97.5), "KR": (33.0, 38.7, 124.5, 132.0),
}  # fmt: skip


def test_every_shipped_city_sits_inside_its_country(geo_index: GeoIndex) -> None:
    misplaced = []
    for entries in geo_index.by_city.values():
        for entry in entries:
            box = _COUNTRY_BOXES.get(entry.country)
            assert box is not None, f"add a bounding box for {entry.country} ({entry.city})"
            lat_min, lat_max, lon_min, lon_max = box
            if not (lat_min <= entry.lat <= lat_max and lon_min <= entry.lon <= lon_max):
                misplaced.append(f"{entry.city} {entry.country} ({entry.lat}, {entry.lon})")
    assert not misplaced, "coordinates outside their country: " + "; ".join(misplaced)
