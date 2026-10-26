"""Offline unit tests for tools/probe_ats.py's pure functions — no network."""

from datetime import UTC, datetime

import pytest
from tools.probe_ats import (
    Family,
    ProbeResult,
    Verdict,
    _job_count,
    endpoint,
    find_portals,
    format_yaml_entry,
    generate_candidates,
    read_names,
    slugify,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Optiver", "optiver"),
        ("D. E. Shaw", "d-e-shaw"),
        ("SIG (Susquehanna)", "sig-susquehanna"),
        ("3Red Trading", "3red-trading"),
    ],
)
def test_slugify(name: str, expected: str) -> None:
    assert slugify(name) == expected


def test_generate_candidates_puts_guess_first() -> None:
    candidates = generate_candidates("Optiver", guess="optiverus")
    assert candidates[0] == "optiverus"
    assert "optiver" in candidates


def test_generate_candidates_has_no_duplicates() -> None:
    candidates = generate_candidates("Jane Street")
    assert len(candidates) == len(set(candidates))


def test_endpoint_greenhouse_shape() -> None:
    url = endpoint(Family.GREENHOUSE, "optiverus")
    assert url == "https://boards-api.greenhouse.io/v1/boards/optiverus/jobs?content=true"


def test_job_count_greenhouse() -> None:
    body = b'{"jobs": [{"id": 1}, {"id": 2}]}'
    assert _job_count(Family.GREENHOUSE, body) == 2


def test_job_count_greenhouse_empty_board() -> None:
    body = b'{"jobs": []}'
    assert _job_count(Family.GREENHOUSE, body) == 0


def test_job_count_lever_is_a_bare_list() -> None:
    body = b"[{}, {}, {}]"
    assert _job_count(Family.LEVER, body) == 3


def test_job_count_unparsable_payload_is_none() -> None:
    assert _job_count(Family.GREENHOUSE, b"<html>not json</html>") is None


def test_format_yaml_entry_found_is_enabled() -> None:
    result = ProbeResult(
        Family.GREENHOUSE,
        "optiverus",
        Verdict.FOUND,
        163,
        200,
        "https://x",
        None,
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    text = format_yaml_entry(
        slug="optiver",
        name="Optiver",
        sector="prop_trading",
        country="NL",
        priority=1,
        result=result,
    )
    assert "enabled: true" in text
    assert 'token: "optiverus"' in text
    assert "[À CONFIRMER]" not in text


def test_format_yaml_entry_not_found_is_disabled_and_flagged() -> None:
    text = format_yaml_entry(
        slug="acme", name="Acme", sector="vendor", country="US", priority=2, result=None
    )
    assert "enabled: false" in text
    assert "[À CONFIRMER]" in text
    assert "source: custom" in text


def test_format_yaml_entry_empty_board_is_disabled_and_flagged() -> None:
    result = ProbeResult(
        Family.LEVER,
        "acme",
        Verdict.EMPTY,
        0,
        200,
        "https://x",
        None,
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    text = format_yaml_entry(
        slug="acme", name="Acme", sector="vendor", country="US", priority=2, result=result
    )
    assert "enabled: false" in text
    assert "[À CONFIRMER]" in text
    assert "board vide" in text


def test_job_count_pinpoint() -> None:
    assert _job_count(Family.PINPOINT, b'{"data": [{"id": "1"}, {"id": "2"}]}') == 2


def test_format_yaml_entry_pinpoint_is_a_custom_entry_reading_the_json_feed() -> None:
    result = ProbeResult(
        Family.PINPOINT,
        "systematica",
        Verdict.FOUND,
        5,
        200,
        "https://x",
        None,
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    text = format_yaml_entry(
        slug="systematica",
        name="Systematica",
        sector="hedge_fund",
        country="GB",
        priority=1,
        result=result,
    )
    assert "source: custom" in text
    assert 'api: "https://systematica.pinpointhq.com/postings.json"' in text
    assert "items: data" in text
    assert "enabled: true" in text


def test_find_portals_reads_an_oracle_hcm_host_and_site() -> None:
    html = (
        '<a href="https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/'
        'requisitions">Jobs</a>'
    )
    assert find_portals(html) == {"oracle_hcm": {"jpmc.fa.oraclecloud.com/cx_1001"}}


def test_find_portals_reads_a_numbered_oracle_apex() -> None:
    html = "https://acme.fa.ocs.oraclecloud26.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs"
    assert find_portals(html) == {"oracle_hcm": {"acme.fa.ocs.oraclecloud26.com/cx_1"}}


@pytest.mark.parametrize(
    ("html", "portal", "match"),
    [
        ("https://mlp.eightfold.ai/careers", "eightfold", "mlp"),
        ("https://systematica.pinpointhq.com/", "pinpoint", "systematica"),
        ("https://careers-gtsx.icims.com/jobs/search", "icims", "careers-gtsx"),
        ("https://bloomberg.avature.net/careers", "avature", "bloomberg"),
        ("https://socgen.taleo.net/careersection/", "taleo", "socgen"),
        ("https://keplercheuvreux.teamtailor.com/jobs", "teamtailor", "keplercheuvreux"),
        (
            "https://career5.successfactors.eu/career?company=x",
            "successfactors",
            "career5.successfactors.eu",
        ),
    ],
)
def test_find_portals_recognises_each_custom_family(html: str, portal: str, match: str) -> None:
    assert find_portals(html) == {portal: {match}}


def test_find_portals_on_a_page_with_no_portal_is_empty() -> None:
    assert find_portals("<html><a href='/careers'>Careers</a></html>") == {}


def test_read_names_skips_blanks_and_comments() -> None:
    assert read_names("Optiver\n\n# prop shops\nIMC  # Amsterdam\n") == ["Optiver", "IMC"]


def test_find_portals_ignores_eightfolds_asset_host() -> None:
    html = '<script src="https://app.eightfold.ai/widget.js"></script> https://mlp.eightfold.ai/careers'
    assert find_portals(html) == {"eightfold": {"mlp"}}
