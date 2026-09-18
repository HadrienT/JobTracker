"""The golden corpus, scored — blueprint/wp/WP05-match.md §6.

Unlike `test_golden_corpus.py`'s `expect.role_family`/`expect.seniority`/etc,
which were each read off the real posting by hand, `expect.tier` is not an
independent oracle: computing a score by hand against a 13-weight formula
would not be a more trustworthy ground truth than running the formula
itself. It is a frozen regression baseline instead — recorded once by
running `evaluate()` and spot-checked by hand across a representative sample
(the title-based hard rejects, the intern/graduate strong matches, the
title-ambiguous low scores) — so a change in `match` or `configs/profile.yaml`
that shifts a real posting's tier shows up here, on purpose, instead of
silently.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobtracker.collect.registry import load_registry
from jobtracker.core.clock import freeze
from jobtracker.core.enums import Source, Tier
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import RawPosting
from jobtracker.match.profile import Profile, load_profile
from jobtracker.match.score import evaluate
from jobtracker.normalize.cascade import normalize
from jobtracker.normalize.taxonomy import Taxonomy

pytestmark = pytest.mark.golden

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = REPO_ROOT / "tests" / "fixtures" / "postings" / "corpus.jsonl"
_FETCHED_AT = datetime(2026, 1, 1, tzinfo=UTC)


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
        fetched_at=_FETCHED_AT,
        content_hash=entry["id"],
    )


@pytest.fixture(scope="module")
def profile() -> Profile:
    boards = load_registry(REPO_ROOT / "configs" / "companies.yaml")
    company_tiers = {b.company_slug: b.priority for b in boards}
    return load_profile(REPO_ROOT / "configs" / "profile.yaml", company_tiers=company_tiers)


def test_golden_corpus_tier_matches_the_frozen_baseline(
    taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    corpus = _load_corpus()
    mismatches = []

    for entry in corpus:
        raw = _to_raw_posting(entry)
        expect = entry["expect"]
        hq_country = expect["locations"][0]["country"] if expect["locations"] else None
        with freeze(_FETCHED_AT):
            posting = normalize(raw, taxonomy=taxonomy, geo=geo_index, hq_country=hq_country)
            verdict = evaluate(posting, profile=profile)
        if verdict.tier.value != expect["tier"]:
            mismatches.append(f"{entry['id']}: got {verdict.tier.value}, expected {expect['tier']}")

    print(f"\n{len(corpus) - len(mismatches)}/{len(corpus)} tiers match the frozen baseline")
    assert not mismatches, "tier regression: " + "; ".join(mismatches)


def test_golden_corpus_invariant_i5(
    taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    for entry in _load_corpus():
        raw = _to_raw_posting(entry)
        expect = entry["expect"]
        hq_country = expect["locations"][0]["country"] if expect["locations"] else None
        with freeze(_FETCHED_AT):
            posting = normalize(raw, taxonomy=taxonomy, geo=geo_index, hq_country=hq_country)
            verdict = evaluate(posting, profile=profile)
        is_rejected = verdict.tier == Tier.REJECTED
        assert is_rejected == (verdict.rejection_reason is not None), entry["id"]
