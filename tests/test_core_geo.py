from pathlib import Path

import pytest

from jobtracker.core.enums import RemoteMode
from jobtracker.core.errors import ConfigError
from jobtracker.core.geo import build_geo_index, load_geo_index, resolve_city, resolve_location


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
    index = build_geo_index({"cities": [{"city": "Paris", "country": "FR", "region": "emea"}]})
    assert resolve_city(index, "Nowheresville", hq_country=None) is None


def test_resolve_location_unknown_place_preserves_raw_text() -> None:
    index = build_geo_index({"cities": [{"city": "Paris", "country": "FR", "region": "emea"}]})
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
        {"cities": [{"city": "New York", "country": "US", "region": "amer", "aliases": ["NYC"]}]}
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
