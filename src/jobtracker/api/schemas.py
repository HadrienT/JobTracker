"""Public wire schemas — distinct from `store`'s internal DTOs on purpose
(blueprint/wp/WP07-api.md §2): a rename inside `store` must never silently
change what the front already depends on.
"""

from decimal import Decimal

from pydantic import BaseModel

from jobtracker.core.enums import (
    RemoteMode,
    RoleFamily,
    SalaryPeriod,
    Seniority,
    Source,
    Tier,
    VisaStatus,
)
from jobtracker.core.models import Reason
from jobtracker.store.postings import PostingAliasRow, PostingRow


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
    alias_count: int
    favorited: bool
    hidden: bool

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
            alias_count=row.alias_count,
            favorited=row.is_favorite,
            hidden=row.is_hidden,
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


class PostingDetailOut(PostingOut):
    description: str | None
    reasons: tuple[Reason, ...]
    rejection_reason: str | None
    aliases: tuple[AliasOut, ...]


class PostingsPage(BaseModel):
    items: tuple[PostingOut, ...]
    next_cursor: str | None


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
