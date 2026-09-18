"""Health snapshot for `GET /health` — blueprint/07-ERRORS-AND-LOGGING.md §5.

The full reversed-watchdog engine (blueprint/07-ERRORS-AND-LOGGING.md §4) —
including `source_stalled`, which needs each source's configured interval
from `configs/sources.yaml` — is `runtime/watchdog.py`'s job (WP08), which
will also wire this into `just status`'s exit code and the live collection
loop. This module computes the three alert kinds that need no external
config (`source_mute`, `volume_drop`, `feed_stale`) from data `store`
already owns, so WP07's `/health` route has something real to show before
WP08 exists — and so both eventually read the same facts.
"""

import sqlite3
import statistics
from datetime import UTC, datetime

from pydantic import BaseModel

from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Source
from jobtracker.core.models import Company, SourceRun
from jobtracker.store.companies import list_companies
from jobtracker.store.postings import count_active_canonical, newest_first_seen_at
from jobtracker.store.runs import recent_runs

_DEFAULT_EMPTY_RUNS_BEFORE_ALERT = 3
_DEFAULT_GLOBAL_STALE_HOURS = 48
_VOLUME_DROP_RATIO = 0.2  # a drop below 20% of the rolling median is a >80% drop
_RUN_HISTORY_DEPTH = 6
_RUN_LOOKBACK = 50
_OK_STATUSES = frozenset({"ok", "empty"})
_ERROR_STATUSES = frozenset({"error", "blocked"})


class SourceHealth(BaseModel, frozen=True):
    source: Source
    status: str  # "ok" | "degraded" | "disabled" | "unknown"
    last_run_at: str | None = None
    last_count: int | None = None
    boards_ok: int | None = None
    boards_error: int | None = None
    alert: str | None = None


class HealthAlert(BaseModel, frozen=True):
    kind: str
    source: str | None
    since: str


class FeedHealth(BaseModel, frozen=True):
    active_postings: int
    newest_posting_age_h: float | None
    stale: bool


class HealthSnapshot(BaseModel, frozen=True):
    schema_version: int
    feed: FeedHealth
    sources: tuple[SourceHealth, ...]
    alerts: tuple[HealthAlert, ...]


def health_snapshot(
    conn: sqlite3.Connection,
    *,
    global_stale_hours: int = _DEFAULT_GLOBAL_STALE_HOURS,
    empty_runs_before_alert: int = _DEFAULT_EMPTY_RUNS_BEFORE_ALERT,
) -> HealthSnapshot:
    now = utc_now()
    feed = _feed_health(conn, now, global_stale_hours)
    sources, alerts = _sources_health(conn, empty_runs_before_alert)
    if feed.stale:
        alerts = (*alerts, HealthAlert(kind="feed_stale", source=None, since=now.isoformat()))
    return HealthSnapshot(
        schema_version=_schema_version(conn), feed=feed, sources=sources, alerts=alerts
    )


def _schema_version(conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    versions = [
        int(row["version"].split("_", 1)[0]) for row in rows if row["version"][:1].isdigit()
    ]
    return max(versions) if versions else 0


def _feed_health(conn: sqlite3.Connection, now: datetime, global_stale_hours: int) -> FeedHealth:
    active = count_active_canonical(conn)
    newest_raw = newest_first_seen_at(conn)
    if newest_raw is None:
        return FeedHealth(active_postings=active, newest_posting_age_h=None, stale=False)
    newest = datetime.fromisoformat(newest_raw)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=UTC)
    age_h = (now - newest).total_seconds() / 3600
    return FeedHealth(
        active_postings=active, newest_posting_age_h=age_h, stale=age_h > global_stale_hours
    )


def _sources_health(
    conn: sqlite3.Connection, empty_runs_before_alert: int
) -> tuple[tuple[SourceHealth, ...], tuple[HealthAlert, ...]]:
    by_source: dict[Source, list[Company]] = {}
    for company in list_companies(conn):
        by_source.setdefault(company.source, []).append(company)

    sources: list[SourceHealth] = []
    alerts: list[HealthAlert] = []
    for source in sorted(by_source, key=lambda s: s.value):
        health, alert = _one_source_health(conn, source, by_source[source], empty_runs_before_alert)
        sources.append(health)
        if alert is not None:
            alerts.append(alert)
    return tuple(sources), tuple(alerts)


def _one_source_health(
    conn: sqlite3.Connection,
    source: Source,
    boards: list[Company],
    empty_runs_before_alert: int,
) -> tuple[SourceHealth, HealthAlert | None]:
    if not any(b.enabled for b in boards):
        return SourceHealth(source=source, status="disabled"), None

    runs = recent_runs(conn, source, limit=_RUN_LOOKBACK)
    boards_ok, boards_error = _board_counts(runs)
    if not runs:
        return (
            SourceHealth(
                source=source, status="unknown", boards_ok=boards_ok, boards_error=boards_error
            ),
            None,
        )

    aggregate_runs = [r for r in runs if r.company_slug is None]
    latest = aggregate_runs[0] if aggregate_runs else runs[0]
    alert_kind = _detect_alert(aggregate_runs, empty_runs_before_alert)
    status = "degraded" if alert_kind else "ok"

    health = SourceHealth(
        source=source,
        status=status,
        last_run_at=latest.started_at.isoformat(),
        last_count=latest.fetched,
        boards_ok=boards_ok,
        boards_error=boards_error,
        alert=alert_kind,
    )
    alert = (
        HealthAlert(kind=alert_kind, source=source.value, since=latest.started_at.isoformat())
        if alert_kind
        else None
    )
    return health, alert


def _board_counts(runs: list[SourceRun]) -> tuple[int, int]:
    """Each company's *most recent* run status — `runs` is already newest first."""
    latest_status: dict[str, str] = {}
    for run in runs:
        if run.company_slug is not None:
            latest_status.setdefault(run.company_slug, run.status)
    ok = sum(1 for status in latest_status.values() if status in _OK_STATUSES)
    error = sum(1 for status in latest_status.values() if status in _ERROR_STATUSES)
    return ok, error


def _detect_alert(aggregate_runs: list[SourceRun], empty_runs_before_alert: int) -> str | None:
    recent = aggregate_runs[:empty_runs_before_alert]
    if len(recent) == empty_runs_before_alert and all(r.status == "empty" for r in recent):
        return "source_mute"

    if len(aggregate_runs) > 1:
        history = [r.fetched for r in aggregate_runs[1 : 1 + _RUN_HISTORY_DEPTH]]
        if history:
            median = statistics.median(history)
            if median > 0 and aggregate_runs[0].fetched < median * _VOLUME_DROP_RATIO:
                return "volume_drop"

    return None
