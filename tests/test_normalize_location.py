from jobtracker.core.enums import RemoteMode
from jobtracker.core.geo import GeoIndex
from jobtracker.normalize.location import parse_location


def test_city_state_country_resolves_to_one_location(geo_index: GeoIndex) -> None:
    (loc,) = parse_location("New York, NY, United States", geo=geo_index)
    assert (loc.city, loc.country) == ("New York", "US")


def test_alternatives_split_into_three_locations(geo_index: GeoIndex) -> None:
    locations = parse_location("London or New York or Hong Kong", geo=geo_index)
    assert [loc.city for loc in locations] == ["London", "New York", "Hong Kong"]


def test_hybrid_qualifier_is_detected_and_stripped(geo_index: GeoIndex) -> None:
    (loc,) = parse_location("Amsterdam (Hybrid – 3 days in office)", geo=geo_index)
    assert loc.city == "Amsterdam"
    assert loc.remote_mode == RemoteMode.HYBRID


def test_remote_with_region_has_no_invented_city(geo_index: GeoIndex) -> None:
    (loc,) = parse_location("Remote - EMEA", geo=geo_index)
    assert loc.city is None
    assert loc.region == "emea"
    assert loc.remote_mode == RemoteMode.REMOTE


def test_remote_with_country_restriction(geo_index: GeoIndex) -> None:
    (loc,) = parse_location("Remote (US only)", geo=geo_index)
    assert loc.city is None
    assert loc.country == "US"
    assert loc.remote_mode == RemoteMode.REMOTE


def test_placeholder_invents_nothing(geo_index: GeoIndex) -> None:
    (loc,) = parse_location("Multiple locations", geo=geo_index)
    assert loc.city is None
    assert loc.raw == "Multiple locations"


def test_cambridge_disambiguates_via_hq_country(geo_index: GeoIndex) -> None:
    (uk,) = parse_location("Cambridge", geo=geo_index, hq_country="GB")
    (us,) = parse_location("Cambridge", geo=geo_index, hq_country="US")
    assert uk.country == "GB"
    assert us.country == "US"


def test_none_input_preserves_raw_none(geo_index: GeoIndex) -> None:
    (loc,) = parse_location(None, geo=geo_index)
    assert loc.city is None
    assert loc.raw is None


def test_raw_is_always_preserved(geo_index: GeoIndex) -> None:
    text = "Nowheresville, Wonderland"
    (loc,) = parse_location(text, geo=geo_index)
    assert loc.raw == text
    assert loc.city is None
