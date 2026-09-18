"""Workday collector contract tests — blueprint/wp/WP06-collect-ats2.md §5."""

import json
from pathlib import Path

import pytest

from factories_collect import FakeHttpSession
from jobtracker.collect.ats.workday import KnownWorkdaySummary, WorkdayCollector
from jobtracker.collect.http import BUDGET_EXHAUSTED
from jobtracker.core.enums import Source
from jobtracker.core.errors import BoardNotFound, ConfigError, SourceSchemaChanged
from jobtracker.core.hashing import content_hash
from jobtracker.core.models import Board

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "payloads" / "workday"

pytestmark = pytest.mark.contract


def _board(**overrides: object) -> Board:
    base: dict[str, object] = {
        "company_slug": "morgan_stanley",
        "company_name": "Morgan Stanley",
        "source": Source.WORKDAY,
        "token": "ms",
        "extra": {"wd": "5", "site": "External"},
        "sector": "bank",
        "hq_country": "US",
        "priority": 2,
        "enabled": True,
    }
    base.update(overrides)
    return Board(**base)  # type: ignore[arg-type]


def _job(title: str, path: str, *, location: str = "New York, NY") -> dict:
    return {
        "title": title,
        "externalPath": path,
        "locationsText": location,
        "postedOn": "Posted Today",
    }


def _list_page(jobs: list[dict], *, total: int) -> dict:
    return {"total": total, "jobPostings": jobs}


def test_missing_extra_is_a_config_error() -> None:
    board = _board(extra={})
    with pytest.raises(ConfigError):
        WorkdayCollector().fetch(board, FakeHttpSession())


def test_nominal_response_with_real_fixtures() -> None:
    list_payload = json.loads((FIXTURES / "morgan_stanley_list.json").read_text())
    detail_payload = json.loads((FIXTURES / "morgan_stanley_detail.json").read_text())
    # Only the first summary's title ("Registered Client Service Associate")
    # is not tech/quant-flavored, so it will be skipped by the title
    # pre-filter regardless — feed it as the sole page to force a detail
    # fetch and prove the wiring end-to-end.
    first_job = list_payload["jobPostings"][0]
    first_job["title"] = "Registered Client Service Software Engineer"
    session = FakeHttpSession(responses=[_list_page([first_job], total=1), detail_payload])

    result = WorkdayCollector().fetch(_board(), session)

    assert result.requests_made == 2
    assert result.truncated is False
    assert len(result.postings) == 1
    posting = result.postings[0]
    assert posting.title_raw == "Registered Client Service Software Engineer"
    assert posting.description_raw == detail_payload["jobPostingInfo"]["jobDescription"]
    assert posting.posted_at_raw == "2026-09-17"


def test_pagination_across_three_pages_collects_everything() -> None:
    page1 = _list_page([_job("Branch Administrator", "/job/1")], total=3)
    page2 = _list_page([_job("Teller", "/job/2")], total=3)
    page3 = _list_page([_job("Loan Officer", "/job/3")], total=3)
    session = FakeHttpSession(responses=[page1, page2, page3])

    result = WorkdayCollector().fetch(_board(), session)

    assert result.requests_made == 3
    assert len(result.postings) == 3
    assert {p.source_job_id for p in result.postings} == {"/job/1", "/job/2", "/job/3"}


def test_total_inconsistent_with_served_pages_stops_cleanly() -> None:
    # `total` claims 100 but the second page comes back empty — must stop,
    # not loop forever.
    page1 = _list_page([_job("Branch Administrator", "/job/1")], total=100)
    page2 = _list_page([], total=100)
    session = FakeHttpSession(responses=[page1, page2])

    result = WorkdayCollector().fetch(_board(), session)

    assert result.requests_made == 2
    assert len(result.postings) == 1
    assert result.truncated is False


def test_budget_exhausted_mid_pagination_keeps_postings_already_collected() -> None:
    page1 = _list_page([_job("Branch Administrator", "/job/1")], total=3)
    session = FakeHttpSession(responses=[page1, BUDGET_EXHAUSTED])

    result = WorkdayCollector().fetch(_board(), session)

    assert result.truncated is True
    assert len(result.postings) == 1


def test_detail_404_keeps_the_posting_without_a_description() -> None:
    page = _list_page([_job("Software Engineer", "/job/1")], total=1)
    session = FakeHttpSession(responses=[page, None], raise_on={1: BoardNotFound("404 on detail")})

    result = WorkdayCollector().fetch(_board(), session)

    assert len(result.postings) == 1
    assert result.postings[0].description_raw == ""
    assert result.requests_made == 2


def test_title_prefilter_skips_the_detail_call_for_an_obviously_unrelated_title() -> None:
    page = _list_page([_job("Branch Administrator", "/job/1")], total=1)
    session = FakeHttpSession(responses=[page])

    result = WorkdayCollector().fetch(_board(), session)

    assert result.requests_made == 1  # only the list call, no detail call
    assert len(result.postings) == 1
    assert result.postings[0].description_raw == ""


def test_unchanged_posting_skips_the_detail_call() -> None:
    job = _job("Software Engineer", "/job/1", location="Chicago, IL")
    page = _list_page([job], total=1)
    session = FakeHttpSession(responses=[page])

    summary_hash = content_hash("Software Engineer", "", "Chicago, IL")
    known = {
        ("morgan_stanley", "/job/1"): KnownWorkdaySummary(
            summary_hash=summary_hash, description_raw="Cached description."
        )
    }

    result = WorkdayCollector(known=known).fetch(_board(), session)

    assert result.requests_made == 1  # only the list call
    assert result.postings[0].description_raw == "Cached description."


def test_unrecognizable_list_payload_raises_schema_changed() -> None:
    session = FakeHttpSession(responses=[{"unexpected": "shape"}])
    with pytest.raises(SourceSchemaChanged):
        WorkdayCollector().fetch(_board(), session)


def test_unrecognizable_detail_payload_raises_schema_changed() -> None:
    page = _list_page([_job("Software Engineer", "/job/1")], total=1)
    session = FakeHttpSession(responses=[page, {"unexpected": "shape"}])
    with pytest.raises(SourceSchemaChanged):
        WorkdayCollector().fetch(_board(), session)


def test_empty_board_is_zero_postings_no_exception() -> None:
    session = FakeHttpSession(responses=[_list_page([], total=0)])
    result = WorkdayCollector().fetch(_board(), session)
    assert result.postings == ()
