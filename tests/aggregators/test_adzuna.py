"""Adzuna collector — WP13 §3.1. Payload shape from Adzuna's public API documentation."""

import json

import pytest
from factories_aggregators import TextSession

from jobtracker.collect.aggregators.adzuna import AdzunaCollector
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceBlocked, SourceSchemaChanged
from jobtracker.core.models import Board

pytestmark = pytest.mark.contract

_RESULT = {
    "id": "4891234567",
    "title": "Graduate Quantitative Developer",
    "description": "Join our trading desk building low latency systems in C++ ...",
    "created": "2026-09-15T08:00:00Z",
    "redirect_url": "https://www.adzuna.co.uk/jobs/details/4891234567",
    "company": {"display_name": "Acme Capital Ltd"},
    "location": {"display_name": "London, UK", "area": ["UK", "London"]},
}


def _board(**extra: str) -> Board:
    return Board(
        company_slug="adzuna:quant-gb",
        company_name="adzuna search",
        source=Source.ADZUNA,
        token="quantitative developer",
        extra={"country": "gb", "max_pages": "1", **extra},
        sector="aggregator",
        hq_country="GB",
        priority=1,
        enabled=True,
    )


def _collector() -> AdzunaCollector:
    return AdzunaCollector(app_id="ID", app_key="KEY")


def test_maps_a_result() -> None:
    session = TextSession([("adzuna", json.dumps({"results": [_RESULT], "count": 1}))])
    result = _collector().fetch(_board(), session)
    (posting,) = result.postings
    assert posting.source == Source.ADZUNA
    assert posting.source_job_id == "4891234567"
    assert posting.company_name == "Acme Capital Ltd"
    assert posting.company_slug == "acme_capital"
    assert posting.location_raw == "London, UK"
    assert posting.posted_at_raw == "2026-09-15T08:00:00Z"
    assert posting.url == _RESULT["redirect_url"]


def test_credentials_and_query_go_in_the_request_not_the_url_path() -> None:
    session = TextSession([("adzuna", json.dumps({"results": []}))])
    _collector().fetch(_board(where="London"), session)
    url, params = session.calls[0]
    assert url == "https://api.adzuna.com/v1/api/jobs/gb/search/1"
    assert params is not None
    assert (params["app_id"], params["app_key"], params["what"], params["where"]) == (
        "ID",
        "KEY",
        "quantitative developer",
        "London",
    )
    assert "KEY" not in url  # the key never lands in a URL that gets logged


def test_a_result_without_an_employer_is_skipped() -> None:
    broken = {**_RESULT, "company": {}}
    session = TextSession([("adzuna", json.dumps({"results": [broken]}))])
    assert _collector().fetch(_board(), session).postings == ()


def test_a_challenge_or_reshaped_payload_is_loud() -> None:
    with pytest.raises(SourceBlocked):
        _collector().fetch(_board(), TextSession([("adzuna", "<title>Just a moment...</title>")]))
    with pytest.raises(SourceSchemaChanged):
        _collector().fetch(_board(), TextSession([("adzuna", json.dumps({"oops": 1}))]))
