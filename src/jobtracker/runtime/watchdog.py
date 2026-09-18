"""The fourth watchdog alert, `source_stalled` — blueprint/07-ERRORS-AND-LOGGING.md §4.

`store.health` already computes `source_mute`, `volume_drop`, and
`feed_stale` from data `store` owns alone. `source_stalled` needs each
source's configured `interval_min` from `configs/sources.yaml`, which
`store` cannot read (contract D2) and `api` cannot either (D6) — `runtime`
is the first layer allowed to import both `collect.http` and `store.health`,
so this is where the fourth alert joins the other three.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

from jobtracker.collect.http import SourcesConfig
from jobtracker.core.clock import utc_now
from jobtracker.store.health import HealthAlert, HealthSnapshot, SourceHealth, health_snapshot

STALLED_INTERVAL_MULTIPLIER = 3


def full_health_snapshot(
    conn: sqlite3.Connection, sources_config: SourcesConfig, *, now: datetime | None = None
) -> HealthSnapshot:
    now = now if now is not None else utc_now()
    snapshot = health_snapshot(conn)

    sources: list[SourceHealth] = []
    stalled_alerts: list[HealthAlert] = []
    for source_health in snapshot.sources:
        updated, alert = _apply_stalled_check(source_health, sources_config, now)
        sources.append(updated)
        if alert is not None:
            stalled_alerts.append(alert)

    return snapshot.model_copy(
        update={"sources": tuple(sources), "alerts": (*snapshot.alerts, *stalled_alerts)}
    )


def _apply_stalled_check(
    source_health: SourceHealth, sources_config: SourcesConfig, now: datetime
) -> tuple[SourceHealth, HealthAlert | None]:
    if source_health.status == "disabled" or source_health.last_run_at is None:
        return source_health, None
    interval_min = sources_config.interval_min.get(str(source_health.source))
    if interval_min is None:
        return source_health, None

    last_run = datetime.fromisoformat(source_health.last_run_at)
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=UTC)
    if now - last_run <= timedelta(minutes=interval_min * STALLED_INTERVAL_MULTIPLIER):
        return source_health, None

    alert = HealthAlert(
        kind="source_stalled", source=str(source_health.source), since=source_health.last_run_at
    )
    updated = source_health.model_copy(
        update={"status": "degraded", "alert": source_health.alert or "source_stalled"}
    )
    return updated, alert
