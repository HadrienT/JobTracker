"""Frozen DTOs shared across packages — see blueprint/03-INTERFACES.md §2.

Every stage produces a new object; none mutates its input. Only the DTOs
defined by that contract live here — ``Company`` and ``SourceRun`` are left
for the packages that pin their shape (WP02/WP07) rather than guessed now.
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, model_validator

from jobtracker.core.enums import (
    RemoteMode,
    RoleFamily,
    SalaryPeriod,
    Seniority,
    Source,
    Tier,
    VisaStatus,
)


class Board(BaseModel, frozen=True):
    """A resolved entry of configs/companies.yaml."""

    company_slug: str
    company_name: str
    source: Source
    token: str
    extra: Mapping[str, str] = {}
    sector: str
    hq_country: str
    priority: int
    enabled: bool


class RawPosting(BaseModel, frozen=True):
    """A posting exactly as served by its source, before normalization."""

    source: Source
    company_slug: str
    source_job_id: str
    url: str
    title_raw: str
    description_raw: str
    location_raw: str | None
    department_raw: str | None
    posted_at_raw: str | None
    payload: bytes
    fetched_at: datetime
    content_hash: str


class Location(BaseModel, frozen=True):
    city: str | None
    country: str | None
    region: str | None
    remote_mode: RemoteMode
    raw: str | None


class Compensation(BaseModel, frozen=True):
    amount_min: Decimal | None
    amount_max: Decimal | None
    currency: str | None
    period: SalaryPeriod | None
    bonus_mentioned: bool
    equity_mentioned: bool
    raw: str | None


class Posting(BaseModel, frozen=True):
    # identity
    posting_id: str
    fingerprint: str
    source: Source
    company_slug: str
    source_job_id: str
    url: str
    # normalized content
    title: str
    role_family: RoleFamily
    seniority: Seniority
    min_years: int | None
    phd_required: bool
    locations: tuple[Location, ...]
    compensation: Compensation
    visa_sponsorship: VisaStatus
    tech: frozenset[str]
    languages_required: frozenset[str]
    # dates — see blueprint/09-CONVENTIONS.md §3
    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    closes_at: datetime | None
    # traceability
    resolver_stage: str
    normalize_version: int


class Reason(BaseModel, frozen=True):
    code: str
    delta: int
    evidence: str | None


class MatchVerdict(BaseModel, frozen=True):
    posting_id: str
    score: int
    tier: Tier
    reasons: tuple[Reason, ...]
    rejection_reason: str | None
    profile_version: int
    scored_at: datetime

    @model_validator(mode="after")
    def _rejection_reason_matches_tier(self) -> "MatchVerdict":
        # Invariant I5 — blueprint/03-INTERFACES.md §2.4.
        if (self.tier == Tier.REJECTED) != (self.rejection_reason is not None):
            raise ValueError("rejection_reason must be set if and only if tier == REJECTED")
        return self
