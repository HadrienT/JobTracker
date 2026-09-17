from datetime import UTC, datetime

import pytest

from jobtracker.core.clock import freeze, utc_now


def test_utc_now_is_aware_utc() -> None:
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() is not None and now.utcoffset().total_seconds() == 0  # type: ignore[union-attr]


def test_freeze_pins_the_clock() -> None:
    pinned = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    with freeze(pinned):
        assert utc_now() == pinned
        assert utc_now() == pinned  # stable across calls within the context


def test_freeze_releases_after_context() -> None:
    pinned = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
    with freeze(pinned):
        pass
    assert utc_now() != pinned


def test_freeze_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError), freeze(datetime(2026, 1, 15, 12, 0)):
        pass
