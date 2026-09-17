"""Source-run repository — blueprint/04-DATA-MODEL.md §2 `source_runs`.

The rows the reversed watchdog (blueprint/07-ERRORS-AND-LOGGING.md §4) reads:
`status='empty'` is a distinct, alarming outcome, not folded into `'ok'`.
"""

import sqlite3

from jobtracker.core.enums import Source
from jobtracker.core.models import SourceRun


def record_run(conn: sqlite3.Connection, run: SourceRun) -> None:
    conn.execute(
        """
        INSERT INTO source_runs (
            run_id, source, company_slug, started_at, ended_at, fetched, new, updated,
            aliased, rejected, requests_made, status, error_kind
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run.run_id,
            run.source.value,
            run.company_slug,
            run.started_at.isoformat(),
            run.ended_at.isoformat(),
            run.fetched,
            run.new,
            run.updated,
            run.aliased,
            run.rejected,
            run.requests_made,
            run.status,
            run.error_kind,
        ),
    )


def recent_runs(conn: sqlite3.Connection, source: Source, limit: int) -> list[SourceRun]:
    """Most recent runs for one source, newest first — feeds the watchdog."""
    rows = conn.execute(
        "SELECT * FROM source_runs WHERE source = ? ORDER BY started_at DESC LIMIT ?",
        (source.value, limit),
    ).fetchall()
    return [_row_to_run(row) for row in rows]


def _row_to_run(row: sqlite3.Row) -> SourceRun:
    return SourceRun(
        run_id=row["run_id"],
        source=Source(row["source"]),
        company_slug=row["company_slug"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        fetched=row["fetched"],
        new=row["new"],
        updated=row["updated"],
        aliased=row["aliased"],
        rejected=row["rejected"],
        requests_made=row["requests_made"],
        status=row["status"],
        error_kind=row["error_kind"],
    )
