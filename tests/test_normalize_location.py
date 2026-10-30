from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from jobtracker.core.enums import RemoteMode
from jobtracker.core.geo import GeoIndex, load_geo_index
from jobtracker.normalize.location import parse_location

_GEO = load_geo_index(Path(__file__).resolve().parents[1] / "configs" / "geo.yaml")
_KNOWN_COUNTRIES = {
    entry.iso for entry in (*_GEO.country_names.values(), *_GEO.country_codes.values())
} | {entry.country for entries in _GEO.by_city.values() for entry in entries}


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


# The unresolved strings of a real collection (143 postings had no city).
def test_an_office_suffix_is_not_part_of_the_city(geo_index: GeoIndex) -> None:
    (loc,) = parse_location("Chicago Office", geo=geo_index)
    assert (loc.city, loc.country) == ("Chicago", "US")


def test_a_city_followed_by_its_country_and_office(geo_index: GeoIndex) -> None:
    (loc,) = parse_location("Dublin Ireland Office", geo=geo_index)
    assert (loc.city, loc.country) == ("Dublin", "IE")


def test_and_and_ampersand_separate_cities(geo_index: GeoIndex) -> None:
    assert [loc.city for loc in parse_location("London and Singapore", geo=geo_index)] == [
        "London",
        "Singapore",
    ]
    assert [loc.city for loc in parse_location("Montreal & Houston", geo=geo_index)] == [
        "Montreal",
        "Houston",
    ]


def test_hanoi_or_ho_chi_minh_city_is_two_cities(geo_index: GeoIndex) -> None:
    locations = parse_location("Hanoi OR Ho Chi Minh City", geo=geo_index)
    assert [(loc.city, loc.country) for loc in locations] == [
        ("Hanoi", "VN"),
        ("Ho Chi Minh City", "VN"),
    ]


def test_a_mixed_string_keeps_every_city_it_can_read(geo_index: GeoIndex) -> None:
    locations = parse_location(
        "Hong Kong Office; Tokyo Office; 臺北市, Taipei, Taiwan", geo=geo_index
    )
    assert {(loc.city, loc.country) for loc in locations} == {
        ("Hong Kong", "HK"),
        ("Tokyo", "JP"),
        ("Taipei", "TW"),
    }


def test_city_state_country_for_the_new_us_cities(geo_index: GeoIndex) -> None:
    for raw, city in [
        ("Jupiter, FL", "Jupiter"),
        ("Miami, Florida, United States", "Miami"),
        ("Sandy, Utah, United States", "Sandy"),
    ]:
        (loc,) = parse_location(raw, geo=geo_index)
        assert (loc.city, loc.country) == (city, "US"), raw


def test_remote_in_a_named_country_keeps_the_country(geo_index: GeoIndex) -> None:
    (loc,) = parse_location("Remote - India", geo=geo_index)
    assert (loc.city, loc.country, loc.remote_mode) == (None, "IN", RemoteMode.REMOTE)


def test_a_sentence_is_not_mined_for_a_city_in_the_middle(geo_index: GeoIndex) -> None:
    (loc,) = parse_location("Flexible, anywhere near London", geo=geo_index)
    assert loc.city is None


@pytest.mark.parametrize(
    ("text", "city", "country"),
    [
        ("Pune, India", "Pune", "IN"),
        ("Plano, TX, United States", "Plano", "US"),
        ("Malvern, PA", "Malvern", "US"),
        ("Quincy, Massachusetts", "Quincy", "US"),
        ("Mississauga Ontario Canada", "Mississauga", "CA"),
        ("Switzerland - Zürich", "Zurich", "CH"),
        ("Basel, Switzerland", "Basel", "CH"),
        ("India - Pune", "Pune", "IN"),
        ("Chennai, IND", "Chennai", "IN"),
        ("GLASGOW, LANARKSHIRE, United Kingdom", "Glasgow", "GB"),
        ("Atlanta, Georgia", "Atlanta", "US"),
        ("Panama City, FL", "Panama City", "US"),
        ("Santa Fe, New Mexico", "Santa Fe", "US"),
        ("Poland", None, "PL"),
        ("US Remote", None, "US"),
        ("IND-BLR-Divyasree Technopolis", None, "IN"),
        ("123 Main Street, Newark, DE, United States", None, "US"),
    ],
)
def test_a_stated_country_is_read_when_the_city_is_unknown(
    geo_index: GeoIndex, text: str, city: str | None, country: str
) -> None:
    (loc,) = parse_location(text, geo=geo_index)
    assert (loc.city, loc.country) == (city, country)


@pytest.mark.parametrize(
    "text",
    ["One Island East", "Headquarters", "2 Locations", "Madison Ave Corp", "Join us", "in, on, at"],
)
def test_no_country_is_invented_for_a_place_that_names_none(geo_index: GeoIndex, text: str) -> None:
    (loc,) = parse_location(text, geo=geo_index)
    assert (loc.city, loc.country) == (None, None)


@given(st.text(max_size=60))
def test_any_text_parses_and_a_country_is_always_a_known_code(text: str) -> None:
    for loc in parse_location(text, geo=_GEO):
        assert loc.country is None or loc.country in _KNOWN_COUNTRIES
