"""SmartRecruiters collector contract tests — blueprint/08-TESTING.md §3."""

import json
from pathlib import Path

import pytest

from factories_collect import FakeHttpSession
from jobtracker.collect.ats.smartrecruiters import SmartRecruitersCollector
from jobtracker.collect.http import BUDGET_EXHAUSTED
from jobtracker.core.enums import Source
from jobtracker.core.errors import BoardNotFound, SourceSchemaChanged
from jobtracker.core.models import Board

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "payloads" / "smartrecruiters" / "flowdesk.json"

pytestmark = pytest.mark.contract


def _board(**overrides: object) -> Board:
    base: dict[str, object] = {
        "company_slug": "flowdesk",
        "company_name": "Flowdesk",
        "source": Source.SMARTRECRUITERS,
        "token": "flowdesk",
        "sector": "crypto",
        "hq_country": "FR",
        "priority": 3,
        "enabled": True,
    }
    base.update(overrides)
    return Board(**base)  # type: ignore[arg-type]


def _detail(job_id: str, text: str = "Full role description.") -> dict:
    return {
        "jobAd": {"sections": {"jobDescription": {"title": "Job Description", "text": text}}},
        "postingUrl": f"https://jobs.smartrecruiters.com/flowdesk/{job_id}",
    }


def test_nominal_response_with_real_fixture() -> None:
    list_payload = json.loads(FIXTURE.read_text())
    detail_responses = [_detail(job["id"]) for job in list_payload["content"]]
    session = FakeHttpSession(responses=[list_payload, *detail_responses])

    result = SmartRecruitersCollector().fetch(_board(), session)

    assert len(result.postings) == len(list_payload["content"])
    first = result.postings[0]
    job = list_payload["content"][0]
    assert first.source_job_id == str(job["id"])
    assert first.title_raw == job["name"]
    assert first.description_raw == "Full role description."
    assert first.location_raw == job["location"]["fullLocation"]


def test_detail_404_keeps_the_posting_without_a_description() -> None:
    list_payload = {"content": [{"id": "1", "name": "Backend Developer"}], "totalFound": 1}
    session = FakeHttpSession(
        responses=[list_payload, None], raise_on={1: BoardNotFound("404 on detail")}
    )
    result = SmartRecruitersCollector().fetch(_board(), session)
    assert len(result.postings) == 1
    assert result.postings[0].description_raw == ""


def test_budget_exhausted_on_list_call_is_not_an_exception() -> None:
    session = FakeHttpSession(responses=[BUDGET_EXHAUSTED])
    result = SmartRecruitersCollector().fetch(_board(), session)
    assert result.truncated is True
    assert result.postings == ()


def test_pagination_across_two_pages() -> None:
    # All list pages are fetched first, then a detail call per collected
    # summary — see SmartRecruitersCollector.fetch's own two-phase order.
    page1 = {"content": [{"id": "1", "name": "Backend Developer"}], "totalFound": 2}
    page2 = {"content": [{"id": "2", "name": "Frontend Developer"}], "totalFound": 2}
    session = FakeHttpSession(responses=[page1, page2, _detail("1"), _detail("2")])
    result = SmartRecruitersCollector().fetch(_board(), session)
    assert {p.source_job_id for p in result.postings} == {"1", "2"}


def test_unrecognizable_list_payload_raises_schema_changed() -> None:
    session = FakeHttpSession(responses=[{"unexpected": "shape"}])
    with pytest.raises(SourceSchemaChanged):
        SmartRecruitersCollector().fetch(_board(), session)


def test_job_missing_a_required_field_is_skipped_run_continues() -> None:
    list_payload = {
        "content": [{"id": "1"}, {"id": "2", "name": "Fine"}],
        "totalFound": 2,
    }
    session = FakeHttpSession(responses=[list_payload, _detail("2")])
    result = SmartRecruitersCollector().fetch(_board(), session)
    assert len(result.postings) == 1
    assert result.postings[0].source_job_id == "2"


def test_empty_board_is_zero_postings_no_exception() -> None:
    session = FakeHttpSession(responses=[{"content": [], "totalFound": 0}])
    result = SmartRecruitersCollector().fetch(_board(), session)
    assert result.postings == ()
