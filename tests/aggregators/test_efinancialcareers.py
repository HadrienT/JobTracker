"""eFinancialCareers collector — WP13 §3.3, §5. The fixture is a real, anonymized API response."""

import json
from pathlib import Path

import pytest
from factories_aggregators import TextSession

from jobtracker.collect.aggregators.efinancialcareers import EfcCollector
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceBlocked, SourceSchemaChanged
from jobtracker.core.models import Board

pytestmark = pytest.mark.contract

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "payloads"
    / "efinancialcareers"
    / "search.json"
)


def _board(**extra: str) -> Board:
    return Board(
        company_slug="efinancialcareers:quant-gb",
        company_name="eFC search",
        source=Source.EFC,
        token="quantitative developer",
        extra={"country": "GB", **extra},
        sector="aggregator",
        hq_country="GB",
        priority=1,
        enabled=True,
    )


def test_maps_the_real_response() -> None:
    payload = json.loads(FIXTURE.read_text())
    session = TextSession([("job-search-ui", json.dumps(payload))])
    result = EfcCollector().fetch(_board(max_pages="1"), session)

    assert len(result.postings) == len(payload["data"])
    first, job = result.postings[0], payload["data"][0]
    assert first.source == Source.EFC
    assert first.source_job_id == job["id"]
    assert first.title_raw == job["title"]
    assert first.url == f"https://www.efinancialcareers.com{job['detailsPageUrl']}"
    assert first.location_raw == job["jobLocation"]["displayName"]
    assert first.company_name == job["companyName"]
    assert first.company_slug == "oxford_knight"
    assert first.posted_at_raw == job["postedDate"]
    assert json.loads(first.payload) == job


def test_query_parameters_are_sent() -> None:
    session = TextSession([("job-search-ui", json.dumps({"data": [], "meta": {}}))])
    EfcCollector().fetch(_board(), session)
    params = session.calls[0][1]
    assert params is not None
    assert (params["q"], params["countryCode2"], params["page"]) == (
        "quantitative developer",
        "GB",
        "1",
    )


def test_pagination_stops_at_the_last_page() -> None:
    payload = json.loads(FIXTURE.read_text())  # meta.pageCount == 2
    session = TextSession([("job-search-ui", json.dumps(payload))])
    result = EfcCollector().fetch(_board(max_pages="5"), session)
    assert len(session.calls) == 2  # not 5
    assert result.requests_made == 2


def test_a_challenge_served_as_200_is_a_block_not_an_empty_run() -> None:
    session = TextSession([("job-search-ui", "<html><title>Human Verification</title></html>")])
    with pytest.raises(SourceBlocked):
        EfcCollector().fetch(_board(), session)


def test_a_reshaped_payload_is_a_schema_change() -> None:
    session = TextSession([("job-search-ui", json.dumps({"results": []}))])
    with pytest.raises(SourceSchemaChanged):
        EfcCollector().fetch(_board(), session)


def test_a_spent_budget_is_truncated_without_an_exception() -> None:
    result = EfcCollector().fetch(_board(), TextSession([("job-search-ui", "")]))
    assert (result.postings, result.truncated) == ((), True)


def test_a_posting_missing_a_required_field_is_skipped() -> None:
    payload = {"data": [{"id": "1", "title": "Quant"}], "meta": {"pageCount": 1}}
    session = TextSession([("job-search-ui", json.dumps(payload))])
    assert EfcCollector().fetch(_board(), session).postings == ()
