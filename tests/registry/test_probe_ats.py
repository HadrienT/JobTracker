"""Offline unit tests for tools/probe_ats.py's pure functions — no network."""

from datetime import UTC, datetime

import pytest
from tools.probe_ats import (
    Family,
    ProbeResult,
    Verdict,
    _job_count,
    endpoint,
    format_yaml_entry,
    generate_candidates,
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
