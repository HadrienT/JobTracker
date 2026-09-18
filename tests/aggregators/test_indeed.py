"""Indeed collector — WP13 §3.4, §5. Synthetic pages: the live site was never probed."""

import json

import pytest
from factories_aggregators import TextSession

from jobtracker.collect.aggregators.indeed import IndeedCollector
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceBlocked, SourceSchemaChanged
from jobtracker.core.models import Board

pytestmark = pytest.mark.contract

_ALLOW_ALL = ("robots.txt", "User-agent: *\nDisallow: /job/\n")


def _page(results: object) -> str:
    model = {"metaData": {"mosaicProviderJobCardsModel": {"results": results}}}
    return (
        "<html><script>window.mosaic.providerData["
        f'"mosaic-provider-jobcards"]={json.dumps(model)};\n</script></html>'
    )


def _board() -> Board:
    return Board(
        company_slug="indeed:quant-london",
        company_name="indeed search",
        source=Source.INDEED,
        token="quantitative developer",
        extra={"domain": "uk.indeed.com", "where": "London"},
        sector="aggregator",
        hq_country="UK",
        priority=1,
        enabled=True,
    )


def test_maps_the_embedded_job_cards() -> None:
    job = {
        "jobkey": "abc123",
        "title": "Quant Developer",
        "company": "Acme Ltd",
        "formattedLocation": "London",
        "snippet": "Build pricing libraries",
        "pubDate": 1789000000000,
    }
    session = TextSession([_ALLOW_ALL, ("/jobs", _page([job]))])
    (posting,) = IndeedCollector().fetch(_board(), session).postings
    assert posting.source == Source.INDEED
    assert posting.source_job_id == "abc123"
    assert posting.company_slug == "acme"
    assert posting.url == "https://uk.indeed.com/viewjob?jk=abc123"
    assert posting.posted_at_raw is not None and posting.posted_at_raw.startswith("2026-")


def test_a_challenge_page_is_a_block_never_an_empty_board() -> None:
    session = TextSession([_ALLOW_ALL, ("/jobs", "<html>Just a moment... cf-chl</html>")])
    with pytest.raises(SourceBlocked):
        IndeedCollector().fetch(_board(), session)


def test_robots_disallowing_the_search_path_is_a_block() -> None:
    session = TextSession([("robots.txt", "User-agent: *\nDisallow: /jobs\n")])
    with pytest.raises(SourceBlocked):
        IndeedCollector().fetch(_board(), session)
    assert len(session.calls) == 1  # it never went on to request the page


def test_a_page_without_the_job_cards_json_is_a_schema_change() -> None:
    session = TextSession([_ALLOW_ALL, ("/jobs", "<html>a redesigned page</html>")])
    with pytest.raises(SourceSchemaChanged):
        IndeedCollector().fetch(_board(), session)


def test_reshaped_job_cards_are_a_schema_change() -> None:
    body = '<script>window.mosaic.providerData["mosaic-provider-jobcards"]={"other":1};</script>'
    session = TextSession([_ALLOW_ALL, ("/jobs", body)])
    with pytest.raises(SourceSchemaChanged):
        IndeedCollector().fetch(_board(), session)
