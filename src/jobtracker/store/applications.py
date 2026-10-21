"""Applications — blueprint/wp/WP21-applications.md §2.

The user's data, like `user_flags`: written by an import, the feed or the CLI, never by the
pipeline. A re-import rewrites what the import knows (dates, status, history) and leaves alone
what only the user knows (the note) and a link to the feed someone set since.
"""

import sqlite3
from collections import defaultdict
from datetime import date

from jobtracker.core.clock import utc_now
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus
from jobtracker.core.models import Application, ApplicationEvent


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def upsert_application(conn: sqlite3.Connection, application: Application) -> None:
    """Insert or refresh one application and replace its history with `application.events`."""
    now = utc_now().isoformat()
    conn.execute(
        """
        INSERT INTO applications (application_id, company, company_slug, title, location,
                                  applied_on, applied_on_estimated, closed_on, status, reason,
                                  posting_id, dossier, origin, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (application_id) DO UPDATE SET
            company = excluded.company, company_slug = excluded.company_slug,
            title = excluded.title, location = excluded.location,
            applied_on = excluded.applied_on,
            applied_on_estimated = excluded.applied_on_estimated,
            closed_on = excluded.closed_on, status = excluded.status, reason = excluded.reason,
            posting_id = COALESCE(applications.posting_id, excluded.posting_id),
            dossier = excluded.dossier, updated_at = excluded.updated_at
        """,
        (
            application.application_id,
            application.company,
            application.company_slug,
            application.title,
            application.location,
            _iso(application.applied_on),
            int(application.applied_on_estimated),
            _iso(application.closed_on),
            application.status.value,
            application.reason,
            application.posting_id,
            application.dossier,
            application.origin.value,
            application.note,
            now,
            now,
        ),
    )
    conn.execute(
        "DELETE FROM application_events WHERE application_id = ?", (application.application_id,)
    )
    conn.executemany(
        "INSERT INTO application_events (application_id, seq, on_date, status, reason) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (application.application_id, seq, _iso(event.on_date), event.status.value, event.reason)
            for seq, event in enumerate(application.events)
        ],
    )


def _events(
    conn: sqlite3.Connection, application_ids: list[str]
) -> dict[str, list[ApplicationEvent]]:
    by_id: dict[str, list[ApplicationEvent]] = defaultdict(list)
    for start in range(0, len(application_ids), 500):
        chunk = application_ids[start : start + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            "SELECT application_id, on_date, status, reason FROM application_events "
            f"WHERE application_id IN ({placeholders}) ORDER BY application_id, seq",
            chunk,
        ).fetchall()
        for row in rows:
            by_id[row["application_id"]].append(
                ApplicationEvent(
                    on_date=_day(row["on_date"]),
                    status=ApplicationStatus(row["status"]),
                    reason=row["reason"],
                )
            )
    return by_id


def _from_row(row: sqlite3.Row, events: list[ApplicationEvent]) -> Application:
    return Application(
        application_id=row["application_id"],
        company=row["company"],
        company_slug=row["company_slug"],
        title=row["title"],
        location=row["location"],
        applied_on=_day(row["applied_on"]),
        applied_on_estimated=bool(row["applied_on_estimated"]),
        closed_on=_day(row["closed_on"]),
        status=ApplicationStatus(row["status"]),
        reason=row["reason"],
        posting_id=row["posting_id"],
        dossier=row["dossier"],
        origin=ApplicationOrigin(row["origin"]),
        note=row["note"],
        events=tuple(events),
    )


def list_applications(conn: sqlite3.Connection) -> list[Application]:
    """Every application, most recent first; undated ones last."""
    rows = conn.execute(
        "SELECT * FROM applications "
        "ORDER BY applied_on IS NULL, applied_on DESC, company, application_id"
    ).fetchall()
    events = _events(conn, [row["application_id"] for row in rows])
    return [_from_row(row, events[row["application_id"]]) for row in rows]


def get_application(conn: sqlite3.Connection, application_id: str) -> Application | None:
    row = conn.execute(
        "SELECT * FROM applications WHERE application_id = ?", (application_id,)
    ).fetchone()
    if row is None:
        return None
    return _from_row(row, _events(conn, [application_id])[application_id])
