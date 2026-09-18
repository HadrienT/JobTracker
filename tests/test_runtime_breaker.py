"""`runtime.breaker.compute_state` contract tests — blueprint/wp/WP08-runtime.md §4."""

from datetime import UTC, datetime, timedelta

from jobtracker.core.enums import Source
from jobtracker.core.models import SourceRun
from jobtracker.runtime.breaker import BreakerStatus, compute_state

_NOW = datetime(2026, 3, 1, tzinfo=UTC)


def _run(status: str, *, minutes_ago: int, fetched: int = 10) -> SourceRun:
    started = _NOW - timedelta(minutes=minutes_ago)
    return SourceRun(
        run_id=f"r-{minutes_ago}",
        source=Source.GREENHOUSE,
        company_slug=None,
        started_at=started,
        ended_at=started,
        fetched=fetched,
        new=0,
        updated=0,
        aliased=0,
        rejected=0,
        requests_made=1,
        status=status,
        error_kind=None,
    )


def test_no_history_is_closed() -> None:
    assert compute_state([], now=_NOW).status == BreakerStatus.CLOSED


def test_a_recent_success_is_closed() -> None:
    runs = [_run("ok", minutes_ago=5)]
    assert compute_state(runs, now=_NOW).status == BreakerStatus.CLOSED


def test_fewer_than_the_threshold_of_failures_stays_closed() -> None:
    runs = [_run("error", minutes_ago=1), _run("error", minutes_ago=2), _run("ok", minutes_ago=3)]
    assert compute_state(runs, now=_NOW, failure_threshold=3).status == BreakerStatus.CLOSED


def test_n_consecutive_failures_opens_the_breaker() -> None:
    runs = [_run("error", minutes_ago=i) for i in (1, 2, 3)]
    state = compute_state(runs, now=_NOW, failure_threshold=3, base_delay_s=30)
    assert state.status == BreakerStatus.OPEN
    assert state.consecutive_failures == 3


def test_a_single_blocked_run_opens_immediately_without_counting_failures() -> None:
    runs = [_run("blocked", minutes_ago=1)]
    state = compute_state(runs, now=_NOW, failure_threshold=3, base_delay_s=1800, max_delay_s=3600)
    assert state.status == BreakerStatus.OPEN
    assert state.consecutive_failures == 1


def test_half_open_once_the_delay_has_elapsed() -> None:
    runs = [_run("blocked", minutes_ago=31)]  # base delay 30s well behind us
    state = compute_state(runs, now=_NOW, base_delay_s=30, max_delay_s=3600)
    assert state.status == BreakerStatus.HALF_OPEN


def test_still_open_before_the_delay_elapses() -> None:
    runs = [_run("blocked", minutes_ago=1)]  # 60s ago < the 30-minute-scale delay below
    state = compute_state(runs, now=_NOW, base_delay_s=1800, max_delay_s=3600)
    assert state.status == BreakerStatus.OPEN


def test_a_failed_half_open_probe_doubles_the_delay() -> None:
    # Two consecutive blocked runs: the second one's delay must reflect
    # 2**(consecutive_failures-1) == 2x the base, not the same delay again.
    first_only = compute_state(
        [_run("blocked", minutes_ago=100)], now=_NOW, base_delay_s=60, max_delay_s=3600
    )
    two_failures = compute_state(
        [_run("blocked", minutes_ago=1), _run("blocked", minutes_ago=100)],
        now=_NOW,
        base_delay_s=60,
        max_delay_s=3600,
    )
    assert first_only.retry_at is not None
    assert two_failures.retry_at is not None
    first_delay = first_only.retry_at - (_NOW - timedelta(minutes=100))
    second_delay = two_failures.retry_at - (_NOW - timedelta(minutes=1))
    assert second_delay == first_delay * 2


def test_delay_is_capped_at_max_delay_s() -> None:
    runs = [_run("error", minutes_ago=i) for i in range(1, 11)]  # 10 consecutive failures
    state = compute_state(runs, now=_NOW, failure_threshold=3, base_delay_s=30, max_delay_s=3600)
    assert state.retry_at is not None
    delay = state.retry_at - (_NOW - timedelta(minutes=1))
    assert delay == timedelta(seconds=3600)


def test_skipped_runs_are_transparent_to_the_computation() -> None:
    with_skips = [
        _run("skipped", minutes_ago=1),
        _run("skipped", minutes_ago=2),
        _run("blocked", minutes_ago=3),
    ]
    without_skips = [_run("blocked", minutes_ago=3)]
    assert compute_state(with_skips, now=_NOW) == compute_state(without_skips, now=_NOW)


def test_recomputing_from_the_same_persisted_runs_gives_the_same_result() -> None:
    # blueprint/wp/WP08-runtime.md §4: a process restart must not reset an
    # open breaker — since state is always recomputed from source_runs, the
    # only thing to verify is that recomputation is itself deterministic.
    runs = [_run("blocked", minutes_ago=1)]
    first = compute_state(runs, now=_NOW, base_delay_s=1800, max_delay_s=3600)
    second = compute_state(runs, now=_NOW, base_delay_s=1800, max_delay_s=3600)
    assert first == second
    assert first.status == BreakerStatus.OPEN
