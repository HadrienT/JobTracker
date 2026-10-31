"""Frozen DTOs shared across packages — see blueprint/03-INTERFACES.md §2.

Every stage produces a new object; none mutates its input. ``Company`` and
``SourceRun`` mirror blueprint/04-DATA-MODEL.md §2 rows (WP02); they were not
guessed ahead of that lot pinning their shape.
"""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, model_validator

from jobtracker.core.enums import (
    ApplicationOrigin,
    ApplicationStatus,
    CvSource,
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


class Company(BaseModel, frozen=True):
    """A `companies` row: the registry, materialized with its running health.

    blueprint/04-DATA-MODEL.md §2: the config file stays the source of truth
    for everything but `last_ok_at`/`last_count`, which only a real collection
    run can produce — the P3 counter.
    """

    company_slug: str
    company_name: str
    source: Source
    token: str
    sector: str
    hq_country: str
    priority: int
    enabled: bool
    last_ok_at: datetime | None
    last_count: int | None
    discovered: bool = False  # seen at an aggregator, absent from configs/companies.yaml


BREAKER_OPEN = "BreakerOpen"


class SourceRun(BaseModel, frozen=True):
    """A `source_runs` row — blueprint/04-DATA-MODEL.md §2.

    `company_slug=None` marks an aggregate run rather than a per-company one.
    `status='empty'` is distinct from `'ok'`: a run with zero postings is the
    event the reversed watchdog (blueprint/07-ERRORS-AND-LOGGING.md §4) exists
    to catch, not a quiet success.
    """

    run_id: str
    source: Source
    company_slug: str | None
    started_at: datetime
    ended_at: datetime
    fetched: int
    new: int
    updated: int
    aliased: int
    rejected: int
    requests_made: int
    status: str  # "ok" | "empty" | "error" | "blocked" | "skipped"
    # A core.errors class name when status is "error"/"blocked"; BREAKER_OPEN on a "skipped"
    # run the breaker refused, None on one where no board was due.
    error_kind: str | None


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
    # Only an aggregator knows the employer as a display name rather than a
    # registry slug (blueprint/03-INTERFACES.md §3.4); an ATS collector leaves it unset.
    company_name: str | None = None


class CollectResult(BaseModel, frozen=True):
    """What one `Collector.fetch()` call returns — blueprint/03-INTERFACES.md §3.1."""

    board: Board
    postings: tuple[RawPosting, ...]
    requests_made: int
    duration_ms: int
    truncated: bool  # True if the request budget cut collection short


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
    title_raw: str  # kept alongside `title`: cleanup is a hypothesis, not a fact
    role_family: RoleFamily
    seniority: Seniority
    min_years: int | None
    phd_required: bool
    locations: tuple[Location, ...]
    compensation: Compensation
    visa_sponsorship: VisaStatus
    visa_evidence: str | None  # the excerpt that justifies visa_sponsorship, from parse_visa
    tech: frozenset[str]
    languages_required: frozenset[str]
    # dates — see blueprint/09-CONVENTIONS.md §3
    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    closes_at: datetime | None
    # traceability
    content_hash: str  # from the source RawPosting: detects a re-fetch with no real change
    resolver_stage: str
    normalize_version: int


class FieldCorrection(BaseModel, frozen=True):
    """One field the LLM changed: the value before, the value after, and the quote behind it."""

    field: str  # a `Posting` attribute name: "compensation", "locations", "seniority", ...
    before: Any
    after: Any
    evidence: str | None
    confidence: float


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


class ApplicationEvent(BaseModel, frozen=True):
    """One step of an application's history — blueprint/wp/WP21-applications.md §2."""

    on_date: date | None
    status: ApplicationStatus
    reason: str = ""


class Application(BaseModel, frozen=True):
    """One application sent for one job, collected posting or not (WP21 §2)."""

    application_id: str
    company: str  # as the user wrote it
    company_slug: str | None  # the registry entry, when the name resolves to one
    title: str | None  # None when the record never said (2024-2025 spreadsheet rows)
    location: str | None
    applied_on: date | None
    applied_on_estimated: bool  # read off the files' timestamps, not written down
    closed_on: date | None
    status: ApplicationStatus
    reason: str  # the user's own words for the outcome, verbatim
    posting_id: str | None
    dossier: str | None  # relative to data/career/applications/
    origin: ApplicationOrigin
    note: str = ""
    events: tuple[ApplicationEvent, ...] = ()
    cv_id: str | None = None  # the CV sent (WP22); None when unknown
    cv_source: CvSource | None = None


class Cv(BaseModel, frozen=True):
    """One CV, by content (blueprint/wp/WP22-cvs.md §2)."""

    cv_id: str  # the SHA-256 of the file
    label: str
    file_name: str  # as it was first seen
    size: int
    pinned: bool  # a version, offered in the menus
    created_at: datetime
    applications: int = 0  # how many used it
