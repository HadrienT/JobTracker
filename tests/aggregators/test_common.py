"""Shared aggregator helpers — blueprint/wp/WP13-aggregators.md §3.4-§5."""

import pytest
from factories_aggregators import TextSession

from factories_store import make_board
from jobtracker.collect.aggregators.common import (
    EmployerIndex,
    RobotsGate,
    get_json_checked,
    normalize_name,
    raise_if_challenge,
    resolver,
    slugify_employer,
)
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceBlocked, SourceSchemaChanged
from jobtracker.core.models import RawPosting

pytestmark = pytest.mark.contract


def _raw(**overrides: object) -> RawPosting:
    base: dict[str, object] = {
        "source": Source.EFC,
        "company_slug": "jane_street_capital",
        "company_name": "Jane Street Capital Ltd.",
        "source_job_id": "1",
        "url": "https://example.com/1",
        "title_raw": "Quant Developer",
        "description_raw": "d",
        "location_raw": "London",
        "department_raw": None,
        "posted_at_raw": None,
        "payload": b"{}",
        "fetched_at": "2026-01-01T00:00:00Z",
        "content_hash": "h",
    }
    base.update(overrides)
    return RawPosting(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Jane Street Ltd.", "jane street"),
        ("Société Générale S.A.", "societe generale"),
        ("  Two   Sigma, LLC ", "two sigma"),
        ("Optiver", "optiver"),
        ("J.P. Morgan & Co.", "jp morgan"),
    ],
)
def test_normalize_name(name: str, expected: str) -> None:
    assert normalize_name(name) == expected


def test_slugify_matches_the_registry_convention() -> None:
    assert slugify_employer("Hudson River Trading LLC") == "hudson_river_trading"
    assert slugify_employer("???") == "unknown"


def test_a_known_employer_resolves_onto_the_registry_slug() -> None:
    index = EmployerIndex([make_board(company_slug="jane_street", company_name="Jane Street")])
    assert index.resolve("Jane Street Capital Ltd.") == (
        "jane_street_capital",
        "Jane Street Capital Ltd.",
    )
    assert index.resolve("JANE STREET Ltd") == ("jane_street", "Jane Street")
    assert index.resolve("jane_street") == ("jane_street", "Jane Street")


def test_the_resolver_rewrites_the_slug_but_leaves_an_ats_posting_alone() -> None:
    resolve = resolver([make_board(company_slug="jane_street", company_name="Jane Street")])
    aggregator = _raw(company_name="Jane Street Ltd", company_slug="jane_street_ltd")
    assert resolve(aggregator).company_slug == "jane_street"
    ats = _raw(company_name=None, company_slug="acme")
    assert resolve(ats) is ats


@pytest.mark.parametrize(
    "body",
    [
        "<html><title>Human Verification</title><script>window.gokuProps = {}</script>",
        "<title>Just a moment...</title>",
        "<div id='px-captcha'></div>",
    ],
)
def test_a_challenge_page_is_a_block(body: str) -> None:
    with pytest.raises(SourceBlocked):
        raise_if_challenge(body, url="https://x")


def test_a_challenge_served_where_json_was_expected_is_a_block_not_a_schema_change() -> None:
    session = TextSession([("api", "<html>Human Verification</html>")])
    with pytest.raises(SourceBlocked):
        get_json_checked(session, "https://api.example/x")


def test_non_json_that_is_not_a_challenge_is_a_schema_change() -> None:
    session = TextSession([("api", "<html>hello</html>")])
    with pytest.raises(SourceSchemaChanged):
        get_json_checked(session, "https://api.example/x")


def test_a_spent_budget_is_none_not_an_error() -> None:
    assert get_json_checked(TextSession([("api", "")]), "https://api.example/x") is None


def test_robots_disallow_is_a_block() -> None:
    session = TextSession([("robots.txt", "User-agent: *\nDisallow: /jobs-guest/\n")])
    gate = RobotsGate(session)
    gate.check("https://www.example.com/allowed")
    with pytest.raises(SourceBlocked):
        gate.check("https://www.example.com/jobs-guest/search")


def test_robots_is_fetched_once_per_host() -> None:
    session = TextSession([("robots.txt", "User-agent: *\nDisallow:\n")])
    gate = RobotsGate(session)
    gate.check("https://h.example/a")
    gate.check("https://h.example/b")
    assert len(session.calls) == 1
