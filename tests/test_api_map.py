"""`/map/pins` and the `place` filter that a pin selects — blueprint/wp/WP17-map.md."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.enums import RemoteMode
from jobtracker.core.models import Location
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting

pytestmark = pytest.mark.db


def _loc(city: str | None, country: str, mode: RemoteMode = RemoteMode.ONSITE) -> Location:
    return Location(city=city, country=country, region=None, remote_mode=mode, raw=city)


def _add(conn: sqlite3.Connection, posting_id: str, *locations: Location) -> None:
    posting = make_posting(
        posting_id=posting_id,
        source_job_id=posting_id,
        fingerprint=f"fp-{posting_id}",
        locations=locations,
    )
    upsert_posting(conn, posting, make_verdict(posting_id=posting_id))
    conn.commit()


@pytest.fixture
def seeded(api_conn: sqlite3.Connection) -> None:
    sync_companies(api_conn, [make_board()])
    _add(api_conn, "p-ldn-1", _loc("London", "GB"))
    _add(api_conn, "p-ldn-2", _loc("London", "GB"))
    _add(api_conn, "p-ldn-on", _loc("London", "CA"))  # the other London
    _add(api_conn, "p-solo", _loc("Paris", "FR"))
    _add(api_conn, "p-multi", _loc("New York", "US"), _loc("London", "GB"))
    _add(api_conn, "p-remote", _loc(None, "US", RemoteMode.REMOTE))  # a country, no city


def _pins(client: TestClient, query: str = "") -> dict:
    response = client.get(f"/map/pins{query}")
    assert response.status_code == 200
    return response.json()


def test_pins_are_counted_per_city_and_tell_homonyms_apart(
    api_client: TestClient, seeded: None
) -> None:
    body = _pins(api_client)
    counts = {(p["country"], p["city"]): p["count"] for p in body["pins"]}
    assert counts == {
        ("GB", "London"): 3,  # two London-only + the one also open in New York
        ("CA", "London"): 1,
        ("FR", "Paris"): 1,
        ("US", "New York"): 1,
    }


def test_a_pin_carries_coordinates_from_the_referential(
    api_client: TestClient, seeded: None
) -> None:
    pins = {(p["country"], p["city"]): p for p in _pins(api_client)["pins"]}
    assert pins[("GB", "London")]["lat"] == pytest.approx(51.5, abs=0.1)
    assert pins[("GB", "London")]["lon"] == pytest.approx(-0.13, abs=0.1)
    assert pins[("CA", "London")]["lon"] < -80  # Ontario, not England


def test_only_a_single_posting_pin_names_its_posting(api_client: TestClient, seeded: None) -> None:
    pins = {(p["country"], p["city"]): p for p in _pins(api_client)["pins"]}
    assert pins[("FR", "Paris")]["posting_id"] == "p-solo"
    assert pins[("GB", "London")]["posting_id"] is None


def test_postings_without_a_city_are_counted_as_unplaced_not_lost(
    api_client: TestClient, seeded: None
) -> None:
    body = _pins(api_client)
    assert body["total"] == 6
    assert body["unplaced"] == 1  # p-remote


def test_a_country_filter_drops_the_pins_of_the_other_countries(
    api_client: TestClient, seeded: None
) -> None:
    # p-multi is open in New York *and* London; filtering on the US must not keep London.
    body = _pins(api_client, "?countries=US")
    assert {(p["country"], p["city"]) for p in body["pins"]} == {("US", "New York")}


def test_the_other_filters_apply_to_the_pins(api_client: TestClient, seeded: None) -> None:
    body = _pins(api_client, "?tech_any=rust")
    assert body["pins"] == []
    assert body["total"] == 0


def test_an_empty_feed_has_no_pins(api_client: TestClient) -> None:
    assert _pins(api_client) == {"pins": [], "total": 0, "unplaced": 0}


def test_the_place_filter_selects_exactly_one_location(
    api_client: TestClient, seeded: None
) -> None:
    response = api_client.get("/postings?place_country=GB&place_city=London")
    ids = {item["posting_id"] for item in response.json()["items"]}
    assert ids == {"p-ldn-1", "p-ldn-2", "p-multi"}  # not the London in Canada


def test_the_place_filter_needs_both_halves(api_client: TestClient) -> None:
    assert api_client.get("/postings?place_city=London").status_code == 422
    assert api_client.get("/postings?place_country=GB").status_code == 422


def test_the_list_behind_a_pin_has_as_many_items_as_the_pin_says(
    api_client: TestClient, seeded: None
) -> None:
    for pin in _pins(api_client)["pins"]:
        query = f"place_country={pin['country']}&place_city={pin['city']}"
        items = api_client.get(f"/postings?{query}").json()["items"]
        assert len(items) == pin["count"], pin
