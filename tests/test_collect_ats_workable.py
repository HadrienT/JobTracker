"""Workable collector contract tests — blueprint/08-TESTING.md §3."""

import json
from pathlib import Path

import pytest

from factories_collect import FakeHttpSession
from jobtracker.collect.ats.workable import WorkableCollector
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceSchemaChanged
from jobtracker.core.models import Board

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "payloads" / "workable" / "eagle_seven.json"

pytestmark = pytest.mark.contract


def _board(**overrides: object) -> Board:
    base: dict[str, object] = {
        "company_slug": "eagle_seven",
        "company_name": "Eagle Seven",
        "source": Source.WORKABLE,
        "token": "eagle-seven",
        "sector": "prop_trading",
        "hq_country": "US",
        "priority": 1,
        "enabled": True,
    }
    base.update(overrides)
    return Board(**base)  # type: ignore[arg-type]


def test_nominal_response_maps_every_field() -> None:
    payload = json.loads(FIXTURE.read_text())
    session = FakeHttpSession(json_response=payload)
    result = WorkableCollector().fetch(_board(), session)

    assert result.requests_made == 1
    assert len(result.postings) == len(payload["jobs"])
    first = result.postings[0]
    job = payload["jobs"][0]
    assert first.source == Source.WORKABLE
    assert first.source_job_id == job["shortcode"]
    assert first.title_raw == job["title"]
    assert first.description_raw == job["description"]
    assert first.location_raw == f"{job['city']}, {job['state']}, {job['country']}"
    assert first.url == job["url"]
    assert first.department_raw == job["department"]


def test_empty_board_is_zero_postings_no_exception() -> None:
    session = FakeHttpSession(json_response={"jobs": []})
    result = WorkableCollector().fetch(_board(), session)
    assert result.postings == ()


def test_unrecognizable_payload_raises_schema_changed() -> None:
    session = FakeHttpSession(json_response={"unexpected": "shape"})
    with pytest.raises(SourceSchemaChanged):
        WorkableCollector().fetch(_board(), session)


def test_job_missing_a_required_field_is_skipped_run_continues() -> None:
    session = FakeHttpSession(
        json_response={
            "jobs": [
                {"title": "No shortcode"},
                {"title": "Fine", "shortcode": "abc", "url": "https://x/abc"},
            ]
        }
    )
    result = WorkableCollector().fetch(_board(), session)
    assert len(result.postings) == 1
    assert result.postings[0].source_job_id == "abc"
