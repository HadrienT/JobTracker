"""Public wire schemas — distinct from `store`'s internal DTOs on purpose
(blueprint/wp/WP07-api.md §2): a rename inside `store` must never silently
change what the front already depends on.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, StringConstraints

from jobtracker.career.countries import application_countries
from jobtracker.career.lifecycle import is_abandoned, is_open, last_news
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
    Triage,
    VisaStatus,
)
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import Application, Cv, Reason
from jobtracker.store.postings import PostingAliasRow, PostingRow

# A note is a reminder, not a document: bounded so one request cannot fill the database.
NOTE_MAX_LENGTH = 4000


class LocationOut(BaseModel):
    city: str | None
    country: str | None
    region: str | None
    remote_mode: RemoteMode
    raw: str | None


class CompensationOut(BaseModel):
    amount_min: Decimal | None
    amount_max: Decimal | None
    currency: str | None
    period: SalaryPeriod | None
    bonus_mentioned: bool
    equity_mentioned: bool
    raw: str | None


class PostingOut(BaseModel):
    posting_id: str
    company_slug: str
    company_name: str
    sector: str
    source: Source
    url: str
    title: str
    title_raw: str
    role_family: RoleFamily
    seniority: Seniority
    min_years: int | None
    phd_required: bool
    locations: tuple[LocationOut, ...]
    compensation: CompensationOut
    visa_sponsorship: VisaStatus
    tech: frozenset[str]
    posted_at: str | None
    first_seen_at: str
    last_seen_at: str
    closes_at: str | None
    score: int
    tier: Tier
    # Why the pipeline set it aside; set if and only if `tier` is `rejected` (invariant I5).
    rejection_reason: str | None
    alias_count: int
    favorited: bool
    hidden: bool
    triage: Triage | None
    application_status: ApplicationStatus | None

    @classmethod
    def from_row(cls, row: PostingRow) -> "PostingOut":
        return cls(
            posting_id=row.posting_id,
            company_slug=row.company_slug,
            company_name=row.company_name,
            sector=row.sector,
            source=row.source,
            url=row.url,
            title=row.title,
            title_raw=row.title_raw,
            role_family=row.role_family,
            seniority=row.seniority,
            min_years=row.min_years,
            phd_required=row.phd_required,
            locations=tuple(LocationOut(**loc.model_dump()) for loc in row.locations),
            compensation=CompensationOut(**row.compensation.model_dump()),
            visa_sponsorship=row.visa_sponsorship,
            tech=row.tech,
            posted_at=row.posted_at_raw,
            first_seen_at=row.first_seen_at_raw,
            last_seen_at=row.last_seen_at_raw,
            closes_at=row.closes_at_raw,
            score=row.score,
            tier=row.tier,
            rejection_reason=row.rejection_reason,
            alias_count=row.alias_count,
            favorited=row.is_favorite,
            hidden=row.is_hidden,
            triage=row.triage,
            application_status=row.application_status,
        )


class AliasOut(BaseModel):
    source: Source
    source_job_id: str
    url: str
    seen_at: str

    @classmethod
    def from_row(cls, row: PostingAliasRow) -> "AliasOut":
        return cls(
            source=row.source, source_job_id=row.source_job_id, url=row.url, seen_at=row.seen_at
        )


class LlmCorrectionOut(BaseModel):
    """A field the local LLM changed on re-reading the posting, with the quote behind it."""

    field: str
    before: Any
    after: Any
    evidence: str | None
    confidence: float
    corrected_at: str


class PostingDetailOut(PostingOut):
    description: str | None
    note: str
    reasons: tuple[Reason, ...]
    aliases: tuple[AliasOut, ...]
    llm_corrections: tuple[LlmCorrectionOut, ...]


class PostingsPage(BaseModel):
    items: tuple[PostingOut, ...]
    next_cursor: str | None


class MapPin(BaseModel):
    city: str
    country: str
    lat: float
    lon: float
    count: int
    # Set only when the pin holds exactly one posting.
    posting_id: str | None


class MapPins(BaseModel):
    pins: tuple[MapPin, ...]
    total: int  # postings matching the filter
    unplaced: int  # of those, the ones with no city to pin (remote, country-only, unresolved)


class StatusRequest(BaseModel):
    """`status: null` stops tracking the posting."""

    status: ApplicationStatus | None


class TriageRequest(BaseModel):
    """`triage: null` puts the posting back in the main feed."""

    triage: Triage | None


class NoteRequest(BaseModel):
    note: Annotated[str, StringConstraints(max_length=NOTE_MAX_LENGTH)]


class CompanyOut(BaseModel):
    company_slug: str
    company_name: str
    sector: str
    hq_country: str
    source: Source
    enabled: bool
    postings_count: int
    last_ok_at: str | None


class FlagRequest(BaseModel):
    value: bool


# --- applications — blueprint/wp/WP21-applications.md -----------------------------------------

_Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
_Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
# A pasted offer: long postings run to ~15 000 characters; bounded all the same.
OFFER_TEXT_MAX_LENGTH = 60_000


class ApplicationEventOut(BaseModel):
    on_date: date | None
    status: ApplicationStatus
    reason: str


class ApplicationFileOut(BaseModel):
    name: str
    path: str  # pass back to GET /applications/{id}/files/{path}
    kind: str  # offer | cv | letter | other
    size: int


class ApplicationOut(BaseModel):
    application_id: str
    company: str
    company_slug: str | None
    title: str | None
    location: str | None
    applied_on: date | None
    applied_on_estimated: bool
    closed_on: date | None
    status: ApplicationStatus
    reason: str
    posting_id: str | None
    origin: ApplicationOrigin
    note: str
    # Derived on every read, never stored (WP21 §2.3): still waiting, and for how long.
    open: bool
    abandoned: bool  # applied/interview with no news for five months
    last_news_on: date | None
    reached_interview: bool
    # ISO 3166-1 alpha-2, read off the location (else the title) — the sheet's colour code.
    countries: tuple[str, ...]
    cv_id: str | None
    cv_source: CvSource | None

    @classmethod
    def from_application(
        cls, application: Application, *, today: date, geo: GeoIndex | None = None
    ) -> "ApplicationOut":
        return cls(
            application_id=application.application_id,
            company=application.company,
            company_slug=application.company_slug,
            title=application.title,
            location=application.location,
            applied_on=application.applied_on,
            applied_on_estimated=application.applied_on_estimated,
            closed_on=application.closed_on,
            status=application.status,
            reason=application.reason,
            posting_id=application.posting_id,
            origin=application.origin,
            note=application.note,
            open=is_open(application, today),
            abandoned=is_abandoned(application, today),
            last_news_on=last_news(application),
            reached_interview=any(
                e.status in {ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER}
                for e in application.events
            )
            or application.status in {ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER},
            countries=application_countries(application.location, application.title, geo=geo),
            cv_id=application.cv_id,
            cv_source=application.cv_source,
        )


class ApplicationDetailOut(ApplicationOut):
    events: tuple[ApplicationEventOut, ...]
    files: tuple[ApplicationFileOut, ...]
    dossier: str | None
    posting_title: str | None
    posting_url: str | None


class CvOut(BaseModel):
    cv_id: str
    label: str
    file_name: str
    size: int
    pinned: bool  # a version, offered in the menus
    created_at: datetime
    applications: int
    current: bool  # the version a new application assumes

    @classmethod
    def from_cv(cls, cv: Cv, *, current: bool) -> "CvOut":
        return cls(**cv.model_dump(), current=current)


class CvEditRequest(BaseModel):
    """Only the fields given change."""

    label: _Name | None = None
    pinned: bool | None = None


class ApplicationCvRequest(BaseModel):
    """The CV sent, as the user says: `null` when it is unknown after all."""

    cv_id: str | None


class ApplicationCreate(BaseModel):
    """An application typed in. `url` of a collected posting links it; `offer_text` (the offer
    pasted) is typeset into the archived offer.pdf. `cv_id` left out assumes the current version
    (inferred); given, even `null`, it is the user's answer."""

    company: _Name
    title: _Name
    location: _Short | None = None
    url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
    applied_on: date | None = None  # default today
    status: ApplicationStatus = ApplicationStatus.APPLIED
    note: Annotated[str, StringConstraints(max_length=NOTE_MAX_LENGTH)] = ""
    offer_text: Annotated[str, StringConstraints(max_length=OFFER_TEXT_MAX_LENGTH)] | None = None
    cv_id: str | None = None


class ApplicationStatusRequest(BaseModel):
    status: ApplicationStatus
    on_date: date | None = None  # default today
    reason: _Short | None = None


class ApplicationEditRequest(BaseModel):
    """Only the fields given change."""

    company: _Name | None = None
    title: _Name | None = None
    location: _Short | None = None
    applied_on: date | None = None
    note: Annotated[str, StringConstraints(max_length=NOTE_MAX_LENGTH)] | None = None


class OfferTextRequest(BaseModel):
    """Re-archive the offer: from this text, else from the linked posting."""

    text: Annotated[str, StringConstraints(max_length=OFFER_TEXT_MAX_LENGTH)] | None = None
    url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None
