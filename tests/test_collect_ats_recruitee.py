"""Recruitee collector contract tests — blueprint/08-TESTING.md §3."""

import json
from pathlib import Path

import pytest

from factories_collect import FakeHttpSession
from jobtracker.collect.ats.recruitee import RecruiteeCollector
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceSchemaChanged
from jobtracker.core.models import Board

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "payloads" / "recruitee" / "sfors.json"

pytestmark = pytest.mark.contract


def _board(**overrides: object) -> Board:
    base: dict[str, object] = {
        "company_slug": "sfors",
        "company_name": "SFORS",
        "source": Source.RECRUITEE,
        "token": "sfors",
        "sector": "prop_trading",
        "hq_country": "AE",
        "priority": 3,
        "enabled": True,
    }
    base.update(overrides)
    return Board(**base)  # type: ignore[arg-type]


def test_nominal_response_maps_every_field() -> None:
    payload = json.loads(FIXTURE.read_text())
    session = FakeHttpSession(json_response=payload)
    result = RecruiteeCollector().fetch(_board(), session)

    assert result.requests_made == 1
    assert len(result.postings) == len(payload["offers"])
    first = result.postings[0]
    offer = payload["offers"][0]
    assert first.source == Source.RECRUITEE
    assert first.source_job_id == str(offer["id"])
    assert first.title_raw == offer["title"]
    assert first.description_raw == offer["description"]
    assert first.url == offer["careers_apply_url"]
    assert "Dubai" in (first.location_raw or "")


def test_empty_board_is_zero_postings_no_exception() -> None:
    session = FakeHttpSession(json_response={"offers": []})
    result = RecruiteeCollector().fetch(_board(), session)
    assert result.postings == ()


def test_unrecognizable_payload_raises_schema_changed() -> None:
    session = FakeHttpSession(json_response={"unexpected": "shape"})
    with pytest.raises(SourceSchemaChanged):
        RecruiteeCollector().fetch(_board(), session)


def test_offer_missing_a_required_field_is_skipped_run_continues() -> None:
    session = FakeHttpSession(
        json_response={
            "offers": [
                {"id": 1, "title": "No URL"},
                {"id": 2, "title": "Fine", "careers_apply_url": "https://x/2"},
            ]
        }
    )
    result = RecruiteeCollector().fetch(_board(), session)
    assert len(result.postings) == 1
    assert result.postings[0].source_job_id == "2"


def test_location_falls_back_to_country_without_a_locations_list() -> None:
    session = FakeHttpSession(
        json_response={
            "offers": [
                {
                    "id": 1,
                    "title": "Backend Developer",
                    "careers_apply_url": "https://x/1",
                    "country": "Poland",
                    "locations": [],
                }
            ]
        }
    )
    result = RecruiteeCollector().fetch(_board(), session)
    assert result.postings[0].location_raw == "Poland"
