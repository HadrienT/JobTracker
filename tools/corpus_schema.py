"""Structural validation of tests/fixtures/postings/corpus.jsonl.

Mirrors the relevant slice of `Posting` from blueprint/03-INTERFACES.md §2.3,
independently of jobtracker.core (WP00 runs in parallel with WP01 — see
tools/registry_schema.py for the same rationale on the company registry).

Two additions beyond the Posting contract, both metadata for corpus curation,
never consumed by the normalizer itself:
- `lang`: the posting's primary language (ISO-639-1), so the golden-corpus
  language quota (blueprint/wp/WP00-recon-registry.md §4) is checkable by code
  instead of by re-reading every entry.
- `company_slug`: links a corpus entry back to configs/companies.yaml, needed
  to check the "5 Software Engineer postings at a prop shop" quota.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

ROLE_FAMILIES = frozenset(
    {"quant_dev", "quant_research", "quant_trading", "swe_platform", "data_eng", "risk", "other"}
)
SENIORITIES = frozenset({"intern", "graduate", "junior", "mid", "senior", "lead", "unknown"})
VISA_STATUSES = frozenset({"sponsors", "no", "unknown"})
REMOTE_MODES = frozenset({"onsite", "hybrid", "remote", "unknown"})
SALARY_PERIODS = frozenset({"year", "month", "day", "hour"})


class ExpectedLocation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    city: str | None
    country: str | None
    remote_mode: str


class ExpectedCompensation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    amount_min: float | None
    amount_max: float | None
    currency: str | None
    period: str | None
    bonus_mentioned: bool
    equity_mentioned: bool


class Expected(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role_family: str
    seniority: str
    min_years: int | None
    phd_required: bool
    locations: list[ExpectedLocation]
    visa_sponsorship: str
    tech: list[str]
    languages_required: list[str]
    compensation: ExpectedCompensation
    closes_at: str | None


class CorpusEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source: str
    company_slug: str
    lang: str
    title_raw: str
    description_raw: str
    location_raw: str | None
    expect: Expected
