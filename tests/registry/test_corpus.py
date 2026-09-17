"""Golden-corpus composition tests — blueprint/wp/WP00-recon-registry.md §4-5.

Checks the quotas that make the corpus useful (not mono-source, not mono-country,
covering the cases that break naive parsers) rather than the normalizer itself:
normalize doesn't exist yet (WP03). Field-level correctness is asserted once
WP03 lands and runs the full cascade against this same file (`just test-golden`).
"""

import json
from pathlib import Path

import yaml
from tools.corpus_schema import CorpusEntry

REPO_ROOT = Path(__file__).parent.parent.parent
CORPUS = REPO_ROOT / "tests" / "fixtures" / "postings" / "corpus.jsonl"
COMPANIES_YAML = REPO_ROOT / "configs" / "companies.yaml"


def _load_corpus() -> list[dict]:
    lines = [line for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def _sector_by_slug() -> dict[str, str]:
    entries = yaml.safe_load(COMPANIES_YAML.read_text(encoding="utf-8"))
    return {e["slug"]: e["sector"] for e in entries}


def test_corpus_loads_and_validates() -> None:
    for raw in _load_corpus():
        CorpusEntry.model_validate(raw)


def test_minimum_size() -> None:
    corpus = _load_corpus()
    assert len(corpus) >= 60, f"expected >= 60 labeled postings, found {len(corpus)}"


def test_ids_are_unique() -> None:
    corpus = _load_corpus()
    ids = [c["id"] for c in corpus]
    assert len(ids) == len(set(ids)), "duplicate id in corpus.jsonl"


def test_spans_at_least_five_ats_families() -> None:
    corpus = _load_corpus()
    families = {c["source"] for c in corpus}
    assert len(families) >= 5, f"expected >= 5 ATS families, found {families}"


def test_spans_at_least_four_countries() -> None:
    corpus = _load_corpus()
    countries = {
        loc["country"] for c in corpus for loc in c["expect"]["locations"] if loc["country"]
    }
    assert len(countries) >= 4, f"expected >= 4 countries, found {countries}"


def test_at_least_ten_without_seniority_mentioned() -> None:
    corpus = _load_corpus()
    count = sum(1 for c in corpus if c["expect"]["seniority"] == "unknown")
    assert count >= 10, f"expected >= 10 postings with seniority=unknown, found {count}"


def test_at_least_ten_with_visa_explicitly_refused() -> None:
    corpus = _load_corpus()
    count = sum(1 for c in corpus if c["expect"]["visa_sponsorship"] == "no")
    assert count >= 10, f"expected >= 10 postings with visa_sponsorship=no, found {count}"


def test_at_least_ten_non_english() -> None:
    corpus = _load_corpus()
    count = sum(1 for c in corpus if c["lang"] != "en")
    assert count >= 10, f"expected >= 10 non-English postings, found {count}"


def test_at_least_five_software_engineer_at_prop_shop() -> None:
    corpus = _load_corpus()
    sectors = _sector_by_slug()
    count = sum(
        1
        for c in corpus
        if "software engineer" in c["title_raw"].lower()
        and sectors.get(c["company_slug"]) == "prop_trading"
    )
    assert count >= 5, f"expected >= 5 'Software Engineer' postings at a prop shop, found {count}"


def test_at_least_five_multi_site() -> None:
    corpus = _load_corpus()
    count = sum(1 for c in corpus if len(c["expect"]["locations"]) > 1)
    assert count >= 5, f"expected >= 5 multi-site postings, found {count}"


def test_at_least_five_with_salary_range() -> None:
    corpus = _load_corpus()
    count = sum(1 for c in corpus if c["expect"]["compensation"]["amount_min"] is not None)
    assert count >= 5, f"expected >= 5 postings with a disclosed salary range, found {count}"


def test_a_few_out_of_scope_postings() -> None:
    corpus = _load_corpus()
    count = sum(1 for c in corpus if c["expect"]["role_family"] == "other")
    assert count >= 3, f"expected a handful of role_family=other postings, found {count}"
