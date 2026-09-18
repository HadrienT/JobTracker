"""Invariant I3, exhaustive on the golden corpus — blueprint/wp/WP12-match-llm.md §5.

`test_golden_corpus_tier_matches_the_frozen_baseline` (test_golden_match.py)
already established that the deterministic pipeline alone reaches the
labeled tier for every entry in the corpus. I3's exhaustive check follows
directly from that: for any entry the prefilter screens out (`is_ambiguous`
is `False`), the tier it reached without any LLM help must still be the
labeled one — the prefilter must never have skipped a call that a real
residual case would have needed.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobtracker.collect.registry import load_registry
from jobtracker.core.clock import freeze
from jobtracker.core.enums import Source
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import RawPosting
from jobtracker.match.prefilter import is_ambiguous
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


def test_i3_no_screened_out_posting_would_have_changed_tier(
    taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    corpus = _load_corpus()
    screened_out = 0
    would_have_changed_tier = []

    for entry in corpus:
        raw = _to_raw_posting(entry)
        expect = entry["expect"]
        hq_country = expect["locations"][0]["country"] if expect["locations"] else None
        with freeze(_FETCHED_AT):
            posting = normalize(raw, taxonomy=taxonomy, geo=geo_index, hq_country=hq_country)
            verdict = evaluate(posting, profile=profile)
            ambiguous = is_ambiguous(
                posting, verdict, profile=profile, description=entry["description_raw"]
            )
        if ambiguous:
            continue
        screened_out += 1
        if verdict.tier.value != expect["tier"]:
            would_have_changed_tier.append(
                f"{entry['id']}: got {verdict.tier.value}, expected {expect['tier']}"
            )

    print(f"\n{screened_out}/{len(corpus)} entries screened out by the prefilter")
    assert not would_have_changed_tier, "I3 violation: " + "; ".join(would_have_changed_tier)
