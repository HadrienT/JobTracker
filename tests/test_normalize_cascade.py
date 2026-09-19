from datetime import UTC, datetime

from jobtracker.core.enums import RoleFamily, Seniority, Source, VisaStatus
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import RawPosting
from jobtracker.normalize.cascade import NORMALIZE_VERSION, normalize
from jobtracker.normalize.taxonomy import Taxonomy


def _raw(**overrides: object) -> RawPosting:
    base: dict[str, object] = {
        "source": Source.GREENHOUSE,
        "company_slug": "acme",
        "source_job_id": "123",
        "url": "https://example.com/jobs/123",
        "title_raw": "Quantitative Developer (F/H) — 2027 Start",
        "description_raw": "Join our trading team. 2+ years of experience with C++.",
        "location_raw": "Paris, France",
        "department_raw": None,
        "posted_at_raw": "2026-01-01T00:00:00Z",
        "payload": b"{}",
        "fetched_at": datetime(2026, 1, 5, tzinfo=UTC),
        "content_hash": "hash-1",
    }
    base.update(overrides)
    return RawPosting(**base)  # type: ignore[arg-type]


def test_normalize_produces_a_fully_populated_posting(
    taxonomy: Taxonomy, geo_index: GeoIndex
) -> None:
    posting = normalize(_raw(), taxonomy=taxonomy, geo=geo_index, hq_country="FR")
    assert posting.role_family == RoleFamily.QUANT_DEV
    assert posting.title == "Quantitative Developer"
    assert posting.title_raw == "Quantitative Developer (F/H) — 2027 Start"
    assert posting.seniority == Seniority.JUNIOR
    assert posting.min_years == 2
    assert posting.locations[0].city == "Paris"
    assert "cpp" in posting.tech
    assert posting.content_hash == "hash-1"
    assert posting.normalize_version == NORMALIZE_VERSION
    assert posting.resolver_stage == "rules"


def test_fingerprint_is_invariant_to_gender_marker_and_start_year(
    taxonomy: Taxonomy, geo_index: GeoIndex
) -> None:
    plain = normalize(
        _raw(title_raw="Quantitative Developer", source_job_id="1"),
        taxonomy=taxonomy,
        geo=geo_index,
    )
    noisy = normalize(
        _raw(title_raw="Quantitative Developer (F/H) — 2026 Start", source_job_id="2"),
        taxonomy=taxonomy,
        geo=geo_index,
    )
    assert plain.fingerprint == noisy.fingerprint


def test_determinism_same_input_same_output_twice(taxonomy: Taxonomy, geo_index: GeoIndex) -> None:
    raw = _raw()
    first = normalize(raw, taxonomy=taxonomy, geo=geo_index, hq_country="FR")
    second = normalize(raw, taxonomy=taxonomy, geo=geo_index, hq_country="FR")
    assert first.model_dump() == {**second.model_dump(), "posting_id": first.posting_id}
    assert first.fingerprint == second.fingerprint
    assert first.content_hash == second.content_hash


def test_posted_at_after_fetched_at_is_discarded(taxonomy: Taxonomy, geo_index: GeoIndex) -> None:
    # A source that rewrites its date to look fresh — blueprint/09-CONVENTIONS.md §3.
    raw = _raw(posted_at_raw="2030-01-01T00:00:00Z", fetched_at=datetime(2026, 1, 5, tzinfo=UTC))
    posting = normalize(raw, taxonomy=taxonomy, geo=geo_index)
    assert posting.posted_at is None


def test_empty_description_never_raises(taxonomy: Taxonomy, geo_index: GeoIndex) -> None:
    raw = _raw(description_raw="", title_raw="", location_raw=None, posted_at_raw=None)
    posting = normalize(raw, taxonomy=taxonomy, geo=geo_index)
    assert posting.role_family == RoleFamily.OTHER
    assert posting.visa_sponsorship == VisaStatus.UNKNOWN


def test_first_seen_and_last_seen_come_from_fetched_at(
    taxonomy: Taxonomy, geo_index: GeoIndex
) -> None:
    fetched_at = datetime(2026, 3, 1, tzinfo=UTC)
    posting = normalize(_raw(fetched_at=fetched_at), taxonomy=taxonomy, geo=geo_index)
    assert posting.first_seen_at == fetched_at
    assert posting.last_seen_at == fetched_at
