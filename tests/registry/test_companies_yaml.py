"""Structural tests for configs/companies.yaml — blueprint/wp/WP00-recon-registry.md §5.

Validated against tools.registry_schema.RegistryEntry rather than
jobtracker.core.models.Board: WP00 is parallelizable with WP01
(blueprint/dependencies.md §2) and must not depend on it being finished.
"""

import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from tools.registry_schema import SLUG_RE, VALID_SECTORS, VALID_SOURCES, RegistryEntry

COMPANIES_YAML = Path(__file__).parent.parent.parent / "configs" / "companies.yaml"

ENTRY_BLOCK_RE = re.compile(r"^- slug:.*?(?=^- slug:|\Z)", re.MULTILINE | re.DOTALL)


def _raw_text() -> str:
    return COMPANIES_YAML.read_text(encoding="utf-8")


def _load_entries() -> list[dict]:
    data = yaml.safe_load(_raw_text())
    assert isinstance(data, list), "companies.yaml must be a YAML list"
    return data


def test_file_exists() -> None:
    assert COMPANIES_YAML.exists(), "configs/companies.yaml is missing"


def test_loads_as_registry_entries() -> None:
    entries = _load_entries()
    for raw in entries:
        RegistryEntry.model_validate(raw)


def test_minimum_company_count() -> None:
    entries = _load_entries()
    assert len(entries) >= 150, f"expected >= 150 companies, found {len(entries)}"


def test_rank1_coverage() -> None:
    entries = _load_entries()
    rank1 = [
        e for e in entries if e["sector"] in ("prop_trading", "hedge_fund") and e["priority"] == 1
    ]
    assert len(rank1) >= 25, (
        f"expected >= 25 rank-1 (prop trading + hedge fund) entries, found {len(rank1)}"
    )


def test_slugs_unique_and_snake_case() -> None:
    entries = _load_entries()
    slugs = [e["slug"] for e in entries]
    assert len(slugs) == len(set(slugs)), "duplicate slug in companies.yaml"
    for slug in slugs:
        assert SLUG_RE.match(slug), f"slug {slug!r} is not snake_case"


def test_sectors_and_sources_are_known_values() -> None:
    entries = _load_entries()
    for e in entries:
        assert e["sector"] in VALID_SECTORS, f"{e['slug']}: unknown sector {e['sector']!r}"
        assert e["source"] in VALID_SOURCES, f"{e['slug']}: unknown source {e['source']!r}"


def test_enabled_entries_have_a_verified_token() -> None:
    entries = _load_entries()
    for e in entries:
        if e["enabled"]:
            assert e["token"], f"{e['slug']}: enabled=true but token is empty"


def test_workday_entries_have_site_and_wd_when_enabled() -> None:
    entries = _load_entries()
    for e in entries:
        if e["source"] == "workday" and e["enabled"]:
            extra = e.get("extra") or {}
            assert "site" in extra and "wd" in extra, (
                f"{e['slug']}: workday entry missing extra.site/wd"
            )


def test_unverified_entries_carry_a_confirmation_marker() -> None:
    """Every entry that is not a verified success must say so in a comment (WP00 §2)."""
    text = _raw_text()
    entries = _load_entries()
    blocks = {}
    for block in ENTRY_BLOCK_RE.findall(text):
        m = re.search(r"^- slug:\s*(\S+)", block)
        if m:
            blocks[m.group(1)] = block
    for e in entries:
        block = blocks.get(e["slug"])
        assert block is not None, f"{e['slug']}: could not locate its raw YAML block"
        if not e["enabled"]:
            assert "[À CONFIRMER]" in block, (
                f"{e['slug']}: enabled=false but no [À CONFIRMER] marker"
            )


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RegistryEntry.model_validate(
            {
                "slug": "acme",
                "name": "Acme",
                "source": "custom",
                "token": "",
                "sector": "vendor",
                "hq_country": "US",
                "priority": 1,
                "enabled": False,
                "unexpected_field": "boom",
            }
        )
