from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobtracker.core.enums import Source, Tier
from jobtracker.core.models import Company, MatchVerdict, SourceRun


def _verdict_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "posting_id": "01J000000000000000000000",
        "score": 80,
        "tier": Tier.STRONG,
        "reasons": (),
        "rejection_reason": None,
        "profile_version": 1,
        "scored_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    base.update(overrides)
    return base


def test_rejected_tier_requires_rejection_reason() -> None:
    with pytest.raises(ValidationError):
        MatchVerdict(**_verdict_kwargs(tier=Tier.REJECTED, rejection_reason=None))


def test_non_rejected_tier_forbids_rejection_reason() -> None:
    with pytest.raises(ValidationError):
        MatchVerdict(**_verdict_kwargs(tier=Tier.STRONG, rejection_reason="senior_only"))


def test_rejected_tier_with_reason_is_valid() -> None:
    verdict = MatchVerdict(**_verdict_kwargs(tier=Tier.REJECTED, rejection_reason="senior_only"))
    assert verdict.tier == Tier.REJECTED
    assert verdict.rejection_reason == "senior_only"


def test_dto_is_frozen() -> None:
    verdict = MatchVerdict(**_verdict_kwargs())
    with pytest.raises(ValidationError):
        verdict.score = 10  # type: ignore[misc]


def test_company_carries_the_p3_health_counters() -> None:
    company = Company(
        company_slug="acme",
        company_name="Acme",
        source=Source.GREENHOUSE,
        token="acme",
        sector="vendor",
        hq_country="US",
        priority=1,
        enabled=True,
        last_ok_at=None,
        last_count=None,
    )
    assert company.last_ok_at is None
    assert company.last_count is None


def test_source_run_aggregate_has_no_company_slug() -> None:
    run = SourceRun(
        run_id="01RUN0000000000000000000A",
        source=Source.GREENHOUSE,
        company_slug=None,
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        ended_at=datetime(2026, 1, 1, tzinfo=UTC),
        fetched=0,
        new=0,
        updated=0,
        aliased=0,
        rejected=0,
        requests_made=0,
        status="empty",
        error_kind=None,
    )
    assert run.company_slug is None
    assert run.status == "empty"
