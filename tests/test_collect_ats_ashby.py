"""Ashby collector contract tests — blueprint/08-TESTING.md §3."""

import json
from pathlib import Path

import pytest

from factories_collect import FakeHttpSession
from jobtracker.collect.ats.ashby import AshbyCollector
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceSchemaChanged
from jobtracker.core.models import Board

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "payloads" / "ashby" / "keyrock.json"

pytestmark = pytest.mark.contract


def _board(**overrides: object) -> Board:
    base: dict[str, object] = {
        "company_slug": "keyrock",
        "company_name": "Keyrock",
        "source": Source.ASHBY,
        "token": "keyrock",
        "sector": "crypto",
        "hq_country": "BE",
        "priority": 1,
        "enabled": True,
    }
    base.update(overrides)
    return Board(**base)  # type: ignore[arg-type]


def test_nominal_response_maps_every_field() -> None:
    payload = json.loads(FIXTURE.read_text())
    listed_jobs = [j for j in payload["jobs"] if j.get("isListed") is not False]
    session = FakeHttpSession(json_response=payload)
    result = AshbyCollector().fetch(_board(), session)

    assert result.requests_made == 1
    assert len(result.postings) == len(listed_jobs)
    first = result.postings[0]
    job = listed_jobs[0]
    assert first.source == Source.ASHBY
    assert first.source_job_id == str(job["id"])
    assert first.title_raw == job["title"]
    assert first.url == job["jobUrl"]
    assert first.location_raw == job["location"]


def test_unlisted_job_is_dropped() -> None:
    session = FakeHttpSession(
        json_response={
            "jobs": [
                {
                    "id": "hidden",
                    "title": "Hidden Role",
                    "jobUrl": "https://x/hidden",
                    "isListed": False,
                    "location": "Remote",
                },
                {
                    "id": "visible",
                    "title": "Visible Role",
                    "jobUrl": "https://x/visible",
                    "isListed": True,
                    "location": "Brussels",
                },
            ]
        }
    )
    result = AshbyCollector().fetch(_board(), session)
    assert [p.source_job_id for p in result.postings] == ["visible"]


def test_unrecognizable_payload_raises_schema_changed() -> None:
    session = FakeHttpSession(json_response={"unexpected": "shape"})
    with pytest.raises(SourceSchemaChanged):
        AshbyCollector().fetch(_board(), session)


def test_job_missing_a_required_field_is_skipped_run_continues() -> None:
    session = FakeHttpSession(
        json_response={
            "jobs": [
                {"id": "1", "title": "No URL", "isListed": True},
                {"id": "2", "title": "Fine", "jobUrl": "https://x/2", "isListed": True},
            ]
        }
    )
    result = AshbyCollector().fetch(_board(), session)
    assert len(result.postings) == 1
    assert result.postings[0].source_job_id == "2"


def test_empty_board_is_zero_postings_no_exception() -> None:
    session = FakeHttpSession(json_response={"jobs": []})
    result = AshbyCollector().fetch(_board(), session)
    assert result.postings == ()
