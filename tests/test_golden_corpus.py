"""The golden corpus: per-stage resolution rate — blueprint/08-TESTING.md §2, §4.

Not a test of "does this match my own code's current output" (that would
verify nothing): every `expect` value was read from the real posting by
hand. A drop in any rate here is a regression, never a corpus update.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobtracker.core.enums import Source
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import RawPosting
from jobtracker.normalize.cascade import normalize
from jobtracker.normalize.taxonomy import Taxonomy

pytestmark = pytest.mark.golden

CORPUS_PATH = Path(__file__).parent / "fixtures" / "postings" / "corpus.jsonl"

FLOORS_PATH = Path(__file__).parent / "fixtures" / "postings" / "resolution_floors.json"

# blueprint/wp/WP03-normalize.md §5 — the floors at delivery. The versioned file may only
# ratchet upwards from these (blueprint/wp/WP14-quality.md §2.2).
_DELIVERY_FLOORS = {"title": 0.95, "location": 0.85, "seniority": 0.75, "visa": 0.60}


def _load_floors() -> dict[str, float]:
    raw = json.loads(FLOORS_PATH.read_text(encoding="utf-8"))
    return {stage: float(value) for stage, value in raw.items() if not stage.startswith("_")}


def _load_corpus() -> list[dict]:
    return [
        json.loads(line) for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines() if line
    ]


def _to_raw_posting(entry: dict) -> RawPosting:
    return RawPosting(
        source=Source(entry["source"]),
        company_slug=entry["company_slug"],
        source_job_id=entry["id"],
        url=f"https://example.invalid/{entry['id']}",
        title_raw=entry["title_raw"],
        description_raw=entry["description_raw"],
        location_raw=entry["location_raw"],
        department_raw=None,
        posted_at_raw=None,
        payload=b"",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash=entry["id"],
    )


def _locations_match(actual, expected: list[dict]) -> bool:
    got = sorted((loc.city or "", loc.country or "") for loc in actual)
    want = sorted((loc["city"] or "", loc["country"] or "") for loc in expected)
    return got == want


def _score_corpus(taxonomy: Taxonomy, geo_index: GeoIndex) -> dict[str, tuple[int, int]]:
    corpus = _load_corpus()
    resolved = dict.fromkeys(("title", "location", "seniority", "visa", "compensation"), 0)
    total = len(corpus)

    for entry in corpus:
        raw = _to_raw_posting(entry)
        hq_country = (
            entry["expect"]["locations"][0]["country"] if entry["expect"]["locations"] else None
        )
        posting = normalize(raw, taxonomy=taxonomy, geo=geo_index, hq_country=hq_country)
        expect = entry["expect"]

        if posting.role_family.value == expect["role_family"]:
            resolved["title"] += 1
        if _locations_match(posting.locations, expect["locations"]):
            resolved["location"] += 1
        if (
            posting.seniority.value == expect["seniority"]
            and posting.min_years == expect["min_years"]
        ):
            resolved["seniority"] += 1
        if posting.visa_sponsorship.value == expect["visa_sponsorship"]:
            resolved["visa"] += 1
        exp_comp = expect["compensation"]
        if (posting.compensation.amount_min is not None) == (exp_comp["amount_min"] is not None):
            resolved["compensation"] += 1

    return {stage: (count, total) for stage, count in resolved.items()}


def test_golden_corpus_resolution_rates(taxonomy: Taxonomy, geo_index: GeoIndex) -> None:
    rates = _score_corpus(taxonomy, geo_index)

    floors = _load_floors()

    print("\nétage            résolus   cumul    plancher")
    for stage, (count, total) in rates.items():
        pct = count / total if total else 0.0
        floor = floors.get(stage)
        print(
            f"{stage:<15}  {count:>3}/{total:<3}   {pct:>6.1%}   {floor:.1%}"
            if floor
            else f"{stage:<15}  {count:>3}/{total:<3}   {pct:>6.1%}   —"
        )

    failures = []
    for stage, floor in floors.items():
        count, total = rates[stage]
        rate = count / total if total else 0.0
        if rate < floor:
            failures.append(f"{stage}: {rate:.1%} < floor {floor:.1%}")
    assert not failures, "resolution rate below floor: " + "; ".join(failures)


def test_floors_file_never_falls_below_the_delivery_floors() -> None:
    floors = _load_floors()
    for stage, delivery in _DELIVERY_FLOORS.items():
        assert floors[stage] >= delivery, f"{stage} floor lowered below its delivery value"


def test_golden_corpus_has_no_regression_versus_a_frozen_baseline(
    taxonomy: Taxonomy, geo_index: GeoIndex
) -> None:
    """I2: normalizing the corpus twice, clock frozen, gives identical results."""
    corpus = _load_corpus()
    for entry in corpus:
        raw = _to_raw_posting(entry)
        hq_country = (
            entry["expect"]["locations"][0]["country"] if entry["expect"]["locations"] else None
        )
        first = normalize(raw, taxonomy=taxonomy, geo=geo_index, hq_country=hq_country)
        second = normalize(raw, taxonomy=taxonomy, geo=geo_index, hq_country=hq_country)
        first_dump = first.model_dump(exclude={"posting_id"})
        second_dump = second.model_dump(exclude={"posting_id"})
        assert first_dump == second_dump, f"non-deterministic normalize() for {entry['id']}"
