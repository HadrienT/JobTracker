from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from jobtracker.core.enums import Tier
from jobtracker.core.models import MatchVerdict


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
