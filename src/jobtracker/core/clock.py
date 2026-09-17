"""The project's only source of time — see blueprint/09-CONVENTIONS.md rule N6.

No other module calls ``datetime.now()``. That discipline is what makes the
normalizer's determinism (invariant I2) testable: without a freezable clock,
"published 3 days ago" would drift between two runs of the golden corpus.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

_frozen_at: ContextVar[datetime | None] = ContextVar("_frozen_at", default=None)


def utc_now() -> datetime:
    """Return the current time, aware UTC — or the frozen time under ``freeze()``."""
    frozen = _frozen_at.get()
    return frozen if frozen is not None else datetime.now(UTC)


@contextmanager
def freeze(at: datetime) -> Iterator[None]:
    """Pin ``utc_now()`` to ``at`` for the duration of the context — tests only."""
    if at.tzinfo is None:
        raise ValueError("freeze() requires an aware datetime")
    token = _frozen_at.set(at.astimezone(UTC))
    try:
        yield
    finally:
        _frozen_at.reset(token)
