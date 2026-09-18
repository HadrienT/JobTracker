"""Lever collector contract tests — blueprint/08-TESTING.md §3."""

import json
from pathlib import Path

import pytest

from factories_collect import FakeHttpSession
from jobtracker.collect.ats.lever import LeverCollector
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceSchemaChanged
from jobtracker.core.models import Board

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "payloads" / "lever" / "belvedere_trading.json"

pytestmark = pytest.mark.contract


def _board(**overrides: object) -> Board:
    base: dict[str, object] = {
        "company_slug": "belvedere_trading",
        "company_name": "Belvedere Trading",
        "source": Source.LEVER,
        "token": "belvederetrading",
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
    result = LeverCollector().fetch(_board(), session)

    assert result.requests_made == 1
    assert len(result.postings) == len(payload)
    first = result.postings[0]
    job = payload[0]
    assert first.source == Source.LEVER
    assert first.source_job_id == str(job["id"])
    assert first.title_raw == job["text"]
    assert first.url == job["hostedUrl"]
    assert first.location_raw == job["categories"]["location"]
    assert first.department_raw == job["categories"]["team"]


def test_commitment_survives_in_the_archived_payload() -> None:
    # blueprint/11-SOURCES.md §2: `categories.commitment` ("Full-Time"/"Intern")
    # is precious seniority signal — normalize doesn't read it yet, but the
    # collector must never drop it from what gets archived.
    payload = [
        {
            "id": "abc",
            "text": "Junior Quant Developer",
            "hostedUrl": "https://jobs.lever.co/x/abc",
            "categories": {
                "location": "Chicago, Illinois",
                "commitment": "Intern",
                "team": "Trading",
            },
            "descriptionPlain": "Join us.",
        }
    ]
    session = FakeHttpSession(json_response=payload)
    result = LeverCollector().fetch(_board(), session)
    archived = json.loads(result.postings[0].payload)
    assert archived["categories"]["commitment"] == "Intern"


def test_bare_list_response_is_the_expected_shape_not_an_error() -> None:
    session = FakeHttpSession(json_response=[])
    result = LeverCollector().fetch(_board(), session)
    assert result.postings == ()


def test_enveloped_response_is_schema_changed() -> None:
    # Lever's real shape is a bare list, never `{"postings": [...]}`.
    session = FakeHttpSession(json_response={"postings": []})
    with pytest.raises(SourceSchemaChanged):
        LeverCollector().fetch(_board(), session)


def test_job_missing_a_required_field_is_skipped_run_continues() -> None:
    session = FakeHttpSession(
        json_response=[
            {"id": "1", "text": "No URL"},
            {"id": "2", "text": "Fine", "hostedUrl": "https://x/2", "categories": {}},
        ]
    )
    result = LeverCollector().fetch(_board(), session)
    assert len(result.postings) == 1
    assert result.postings[0].source_job_id == "2"
