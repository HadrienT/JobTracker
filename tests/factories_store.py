"""Builders for core DTOs used across the store test suite — not a test module."""

from datetime import UTC, datetime

from jobtracker.core.enums import (
    RemoteMode,
    RoleFamily,
    Seniority,
    Source,
    Tier,
    VisaStatus,
)
from jobtracker.core.models import Board, Compensation, Location, MatchVerdict, Posting

_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)


def make_board(**overrides: object) -> Board:
    base: dict[str, object] = {
        "company_slug": "acme",
        "company_name": "Acme",
        "source": Source.GREENHOUSE,
        "token": "acme",
        "sector": "vendor",
        "hq_country": "US",
        "priority": 1,
        "enabled": True,
    }
    base.update(overrides)
    return Board(**base)  # type: ignore[arg-type]


def make_posting(**overrides: object) -> Posting:
    base: dict[str, object] = {
        "posting_id": "01J0000000000000000000P1",
        "fingerprint": "fp-1",
        "source": Source.GREENHOUSE,
        "company_slug": "acme",
        "source_job_id": "job-1",
        "url": "https://example.com/jobs/1",
        "title": "Quant Developer",
        "title_raw": "Quant Developer (H/F)",
        "role_family": RoleFamily.QUANT_DEV,
        "seniority": Seniority.JUNIOR,
        "min_years": None,
        "phd_required": False,
        "locations": (
            Location(
                city="Paris", country="FR", region=None, remote_mode=RemoteMode.ONSITE, raw="Paris"
            ),
        ),
        "compensation": Compensation(
            amount_min=None,
            amount_max=None,
            currency=None,
            period=None,
            bonus_mentioned=False,
            equity_mentioned=False,
            raw=None,
        ),
        "visa_sponsorship": VisaStatus.UNKNOWN,
        "visa_evidence": None,
        "tech": frozenset({"python"}),
        "languages_required": frozenset(),
        "posted_at": _EPOCH,
        "first_seen_at": _EPOCH,
        "last_seen_at": _EPOCH,
        "closes_at": None,
        "content_hash": "hash-1",
        "resolver_stage": "rules",
        "normalize_version": 1,
    }
    base.update(overrides)
    return Posting(**base)  # type: ignore[arg-type]


def make_verdict(**overrides: object) -> MatchVerdict:
    base: dict[str, object] = {
        "posting_id": "01J0000000000000000000P1",
        "score": 70,
        "tier": Tier.POSSIBLE,
        "reasons": (),
        "rejection_reason": None,
        "profile_version": 1,
        "scored_at": _EPOCH,
    }
    base.update(overrides)
    return MatchVerdict(**base)  # type: ignore[arg-type]
