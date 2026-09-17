"""Invariant I1: no stage ever raises, on any input — blueprint/08-TESTING.md §4."""

from datetime import UTC, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from jobtracker.core.enums import Source
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import RawPosting
from jobtracker.normalize.cascade import normalize
from jobtracker.normalize.compensation import parse_compensation
from jobtracker.normalize.language import parse_languages_required
from jobtracker.normalize.location import parse_location
from jobtracker.normalize.seniority import parse_seniority
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.normalize.techstack import parse_tech
from jobtracker.normalize.title import classify_role, clean_title
from jobtracker.normalize.visa import parse_visa

pytestmark = pytest.mark.property

# Arbitrary Unicode text, including the empty string and multi-KB blobs, plus
# a raw-bytes-as-text case standing in for "binary text" (08-TESTING.md §4's
# "texte binaire" case — an ATS never hands normalize() actual bytes, since
# RawPosting's text fields are `str`, but mis-decoded binary shows up as this
# kind of surrogate/control-character-laden string).
_TEXT = st.text(max_size=2000)
_BINARY_LIKE_TEXT = st.binary(max_size=500).map(lambda b: b.decode("latin-1"))
_ANY_TEXT = st.one_of(_TEXT, _BINARY_LIKE_TEXT)


@given(text=_ANY_TEXT)
@settings(max_examples=200)
def test_clean_title_never_raises(text: str) -> None:
    clean_title(text)


@given(title=_ANY_TEXT, description=_ANY_TEXT)
@settings(max_examples=200)
def test_classify_role_never_raises(title: str, description: str, taxonomy: Taxonomy) -> None:
    classify_role(title, description, taxonomy=taxonomy)


@given(text=_ANY_TEXT, hq_country=st.one_of(st.none(), st.text(max_size=5)))
@settings(max_examples=200)
def test_parse_location_never_raises(
    text: str, hq_country: str | None, geo_index: GeoIndex
) -> None:
    parse_location(text, geo=geo_index, hq_country=hq_country)


@given(title=_ANY_TEXT, description=_ANY_TEXT)
@settings(max_examples=200)
def test_parse_seniority_never_raises(title: str, description: str, taxonomy: Taxonomy) -> None:
    parse_seniority(title, description, taxonomy=taxonomy)


@given(description=_ANY_TEXT, country=st.one_of(st.none(), st.text(max_size=5)))
@settings(max_examples=200)
def test_parse_compensation_never_raises(description: str, country: str | None) -> None:
    parse_compensation(description, country=country)


@given(description=_ANY_TEXT)
@settings(max_examples=200)
def test_parse_visa_never_raises(description: str, taxonomy: Taxonomy) -> None:
    parse_visa(description, taxonomy=taxonomy)


@given(description=_ANY_TEXT)
@settings(max_examples=200)
def test_parse_tech_never_raises(description: str, taxonomy: Taxonomy) -> None:
    parse_tech(description, taxonomy=taxonomy)


@given(description=_ANY_TEXT)
@settings(max_examples=200)
def test_parse_languages_required_never_raises(description: str, taxonomy: Taxonomy) -> None:
    parse_languages_required(description, taxonomy=taxonomy)


@given(
    title=_ANY_TEXT,
    description=_ANY_TEXT,
    location=st.one_of(st.none(), _ANY_TEXT),
    posted_at_raw=st.one_of(st.none(), _ANY_TEXT),
)
@settings(max_examples=200)
def test_normalize_never_raises_on_arbitrary_text(
    *,
    title: str,
    description: str,
    location: str | None,
    posted_at_raw: str | None,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
) -> None:
    raw = RawPosting(
        source=Source.GREENHOUSE,
        company_slug="acme",
        source_job_id="1",
        url="https://example.com",
        title_raw=title,
        description_raw=description,
        location_raw=location,
        department_raw=None,
        posted_at_raw=posted_at_raw,
        payload=b"{}",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash="hash",
    )
    normalize(raw, taxonomy=taxonomy, geo=geo_index)


def test_200kb_description_never_raises(taxonomy: Taxonomy, geo_index: GeoIndex) -> None:
    huge = "Quantitative Developer role. " * 7000  # ~200 KB
    raw = RawPosting(
        source=Source.GREENHOUSE,
        company_slug="acme",
        source_job_id="1",
        url="https://example.com",
        title_raw="Quantitative Developer",
        description_raw=huge,
        location_raw=None,
        department_raw=None,
        posted_at_raw=None,
        payload=b"{}",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash="hash",
    )
    posting = normalize(raw, taxonomy=taxonomy, geo=geo_index)
    assert posting is not None
