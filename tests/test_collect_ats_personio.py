"""Personio collector contract tests — blueprint/08-TESTING.md §3.

`kaiko.json` is the real fixture WP00 captured — a Personio board that is
technically live but never filled in beyond its Lorem-ipsum template
(blueprint/11-SOURCES.md §3). The synthetic XML below exists only to exercise
`<office>`/`<department>` mapping, which that real board happens not to use.
"""

from pathlib import Path

import pytest

from factories_collect import FakeHttpSession
from jobtracker.collect.ats.personio import PersonioCollector
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceSchemaChanged
from jobtracker.core.models import Board

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "payloads" / "personio" / "kaiko.json"

pytestmark = pytest.mark.contract

_SYNTHETIC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<workzag-jobs>
<position>
    <id>555</id>
    <name>Quantitative Developer</name>
    <office>Berlin</office>
    <department>Engineering</department>
    <jobDescriptions>
        <jobDescription>
            <name>Your mission</name>
            <value><![CDATA[Build our pricing engine.]]></value>
        </jobDescription>
    </jobDescriptions>
    <createdAt>2026-01-15T10:00:00+00:00</createdAt>
</position>
</workzag-jobs>
"""


def _board(**overrides: object) -> Board:
    base: dict[str, object] = {
        "company_slug": "kaiko",
        "company_name": "Kaiko",
        "source": Source.PERSONIO,
        "token": "kaiko",
        "sector": "vendor",
        "hq_country": "FR",
        "priority": 2,
        "enabled": True,
    }
    base.update(overrides)
    return Board(**base)  # type: ignore[arg-type]


def test_synthetic_response_maps_office_and_department() -> None:
    session = FakeHttpSession(text_response=_SYNTHETIC_XML)
    result = PersonioCollector().fetch(_board(), session)

    assert result.requests_made == 1
    assert len(result.postings) == 1
    posting = result.postings[0]
    assert posting.title_raw == "Quantitative Developer"
    assert posting.location_raw == "Berlin"
    assert posting.department_raw == "Engineering"
    assert "Build our pricing engine." in posting.description_raw
    assert posting.url == "https://kaiko.jobs.personio.de/job/555"
    assert posting.posted_at_raw == "2026-01-15T10:00:00+00:00"


def test_real_template_board_is_collected_not_treated_as_an_error() -> None:
    # blueprint/11-SOURCES.md §3: a Personio board technically found can still
    # be a never-filled template — that is P3's problem, not this collector's.
    session = FakeHttpSession(text_response=FIXTURE.read_text())
    result = PersonioCollector().fetch(_board(), session)
    assert len(result.postings) == 3
    assert all(p.location_raw is None for p in result.postings)


def test_malformed_xml_raises_schema_changed() -> None:
    session = FakeHttpSession(text_response="<workzag-jobs><position><unterminated>")
    with pytest.raises(SourceSchemaChanged):
        PersonioCollector().fetch(_board(), session)


def test_empty_body_is_zero_postings_no_exception() -> None:
    session = FakeHttpSession(text_response="")
    result = PersonioCollector().fetch(_board(), session)
    assert result.postings == ()


def test_position_missing_a_required_field_is_skipped_run_continues() -> None:
    xml = """<?xml version="1.0"?>
    <workzag-jobs>
    <position><name>No id</name></position>
    <position><id>1</id><name>Fine</name></position>
    </workzag-jobs>"""
    session = FakeHttpSession(text_response=xml)
    result = PersonioCollector().fetch(_board(), session)
    assert len(result.postings) == 1
    assert result.postings[0].source_job_id == "1"
