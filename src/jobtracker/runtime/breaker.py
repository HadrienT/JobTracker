"""Circuit breaker per source, three states — blueprint/wp/WP08-runtime.md §4.

State is never held in memory: it is *recomputed* from `source_runs` (the
aggregate rows, `company_slug IS NULL`) every time it is needed. That is
what "survives a process restart" means here — there is no separate mutable
breaker object to lose, only the run log the scheduler was already writing.

A `blocked` run opens the breaker immediately, without waiting for N
failures — interdit n°8 applied at the system level. An `error` run only
opens it after `failure_threshold` of them in a row. Any success (`ok` or
`empty` — a 200 with zero postings is not a failure) closes it right away.
`skipped` rows (the breaker was already open and denied the cycle) are
transparent to this computation: they neither open nor close anything.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from jobtracker.core.models import SourceRun

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_BASE_DELAY_S = 30.0
DEFAULT_MAX_DELAY_S = 3600.0

_FAILURE_STATUSES = frozenset({"error", "blocked"})


class BreakerStatus(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class BreakerState:
    status: BreakerStatus
    consecutive_failures: int = 0
    retry_at: datetime | None = None


def compute_state(
    runs: list[SourceRun],
    *,
    now: datetime,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    base_delay_s: float = DEFAULT_BASE_DELAY_S,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
) -> BreakerState:
    """`runs` is one source's aggregate run history, newest first."""
    attempts = [r for r in runs if r.status != "skipped"]
    if not attempts:
        return BreakerState(status=BreakerStatus.CLOSED)

    latest = attempts[0]
    if latest.status not in _FAILURE_STATUSES:
        return BreakerState(status=BreakerStatus.CLOSED)

    consecutive_failures = 0
    for run in attempts:
        if run.status not in _FAILURE_STATUSES:
            break
        consecutive_failures += 1

    tripped = latest.status == "blocked" or consecutive_failures >= failure_threshold
    if not tripped:
        return BreakerState(status=BreakerStatus.CLOSED, consecutive_failures=consecutive_failures)

    delay = min(base_delay_s * (2 ** (consecutive_failures - 1)), max_delay_s)
    retry_at = latest.ended_at + timedelta(seconds=delay)
    status = BreakerStatus.HALF_OPEN if now >= retry_at else BreakerStatus.OPEN
    return BreakerState(status=status, consecutive_failures=consecutive_failures, retry_at=retry_at)
