"""Applications — blueprint/wp/WP21-applications.md §2.

The user's data, like `user_flags`: written by an import, the feed or the CLI, never by the
pipeline. Every write goes through this module, for two reasons:

- **One truth for the feed.** `user_flags.application_status` predates this table (WP18) and
  every feed query filters on it. It is kept, as a *mirror*: after any change to an application
  linked to a posting, `_mirror` rewrites that posting's flag from `applications`. Nothing else
  writes the flag.
- **Hand edits survive a re-import.** A row the import wrote and nobody touched since has
  `updated_at = created_at`; any edit (status, note, link) moves `updated_at`. The import only
  refreshes — or purges — untouched rows.
"""

import re
import sqlite3
import unicodedata
from collections import defaultdict
from datetime import date

from jobtracker.core.clock import utc_now
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus, CvSource
from jobtracker.core.models import Application, ApplicationEvent

_CLOSING = frozenset({ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN})
_SLUG = re.compile(r"[^a-z0-9]+")
_COLUMNS = (
    "application_id, company, company_slug, title, location, applied_on, applied_on_estimated, "
    "closed_on, status, reason, posting_id, dossier, origin, note, created_at, updated_at, "
    "cv_id, cv_source"
)
_PLACEHOLDERS = ", ".join("?" * 18)


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


def _slug(text: str, limit: int) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return _SLUG.sub("-", folded).strip("-")[:limit].strip("-") or "x"


def dossier_name(day: date, company: str, title: str | None) -> str:
    """`2026-10-21-acme-quant-developer`: where a new application's files go."""
    return f"{day.isoformat()}-{_slug(company, 30)}-{_slug(title or 'application', 50)}"


def _values(application: Application, now: str) -> tuple[object, ...]:
    return (
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
        application.cv_id,
        application.cv_source.value if application.cv_source else None,
    )


def _write_events(
    conn: sqlite3.Connection, application_id: str, events: tuple[ApplicationEvent, ...]
) -> None:
    conn.execute("DELETE FROM application_events WHERE application_id = ?", (application_id,))
    conn.executemany(
        "INSERT INTO application_events (application_id, seq, on_date, status, reason) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (application_id, seq, _iso(event.on_date), event.status.value, event.reason)
            for seq, event in enumerate(events)
        ],
    )


def _mirror(conn: sqlite3.Connection, posting_id: str | None) -> None:
    """Rewrite one posting's feed status from the applications linked to it."""
    if posting_id is None:
        return
    row = conn.execute(
        "SELECT status FROM applications WHERE posting_id = ? "
        "ORDER BY updated_at DESC, application_id DESC LIMIT 1",
        (posting_id,),
    ).fetchone()
    status = row["status"] if row is not None else None
    exists = conn.execute("SELECT 1 FROM postings WHERE posting_id = ?", (posting_id,)).fetchone()
    if exists is None:
        return
    now = utc_now().isoformat()
    if status is None:  # clear only: an empty flags row would exempt the posting from retention
        conn.execute(
            "UPDATE user_flags SET application_status = NULL, status_updated_at = ?, "
            "updated_at = ? WHERE posting_id = ? AND application_status IS NOT NULL",
            (now, now, posting_id),
        )
        return
    conn.execute(
        """
        INSERT INTO user_flags (posting_id, is_favorite, is_hidden, updated_at,
                                application_status, status_updated_at)
        VALUES (?, 0, 0, ?, ?, ?)
        ON CONFLICT (posting_id) DO UPDATE SET application_status = excluded.application_status,
            status_updated_at = excluded.status_updated_at, updated_at = excluded.updated_at
        WHERE user_flags.application_status IS NOT excluded.application_status
        """,
        (posting_id, now, status, now),
    )


def create_application(conn: sqlite3.Connection, application: Application) -> None:
    """A new application (feed, CLI). Fails on an existing id: an edit is not a creation."""
    conn.execute(
        f"INSERT INTO applications ({_COLUMNS}) VALUES ({_PLACEHOLDERS})",
        _values(application, utc_now().isoformat()),
    )
    _write_events(conn, application.application_id, application.events)
    _mirror(conn, application.posting_id)


def import_application(conn: sqlite3.Connection, application: Application) -> bool:
    """Insert or refresh one imported application — unless the user changed it since the last
    import, in which case nothing is written and False is returned."""
    now = utc_now().isoformat()
    cursor = conn.execute(
        f"""
        INSERT INTO applications ({_COLUMNS}) VALUES ({_PLACEHOLDERS})
        ON CONFLICT (application_id) DO UPDATE SET
            company = excluded.company, company_slug = excluded.company_slug,
            title = excluded.title, location = excluded.location,
            applied_on = excluded.applied_on,
            applied_on_estimated = excluded.applied_on_estimated,
            closed_on = excluded.closed_on, status = excluded.status, reason = excluded.reason,
            dossier = excluded.dossier,
            created_at = excluded.created_at, updated_at = excluded.updated_at
        WHERE applications.updated_at = applications.created_at
        """,
        _values(application, now),
    )
    if cursor.rowcount == 0:
        return False
    _write_events(conn, application.application_id, application.events)
    return True


def purge_stale_imports(conn: sqlite3.Connection, keep: set[str]) -> tuple[int, int]:
    """Delete imported rows the history no longer produces, unless the user touched them.
    Returns (purged, kept because touched)."""
    rows = conn.execute(
        "SELECT application_id, created_at = updated_at AS untouched FROM applications "
        "WHERE origin = ?",
        (ApplicationOrigin.IMPORT.value,),
    ).fetchall()
    stale = [row for row in rows if row["application_id"] not in keep]
    purge = [row["application_id"] for row in stale if row["untouched"]]
    conn.executemany("DELETE FROM applications WHERE application_id = ?", [(i,) for i in purge])
    return len(purge), len(stale) - len(purge)


def _touch(conn: sqlite3.Connection, application_id: str, **columns: object) -> None:
    sets = ", ".join(f"{name} = ?" for name in columns)
    conn.execute(
        f"UPDATE applications SET {sets}{', ' if sets else ''}updated_at = ? "
        "WHERE application_id = ?",
        (*columns.values(), utc_now().isoformat(), application_id),
    )


def record_status(
    conn: sqlite3.Connection,
    application_id: str,
    status: ApplicationStatus,
    *,
    on_date: date | None,
    reason: str | None = None,
) -> None:
    """One step of the history: appended to the events, and the application's status now."""
    (next_seq,) = conn.execute(
        "SELECT COALESCE(MAX(seq) + 1, 0) FROM application_events WHERE application_id = ?",
        (application_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO application_events (application_id, seq, on_date, status, reason) "
        "VALUES (?, ?, ?, ?, ?)",
        (application_id, next_seq, _iso(on_date), status.value, reason or ""),
    )
    columns: dict[str, object] = {
        "status": status.value,
        "closed_on": _iso(on_date) if status in _CLOSING else None,
    }
    if reason is not None:
        columns["reason"] = reason
    _touch(conn, application_id, **columns)
    _mirror(conn, _posting_of(conn, application_id))


def _posting_of(conn: sqlite3.Connection, application_id: str) -> str | None:
    row = conn.execute(
        "SELECT posting_id FROM applications WHERE application_id = ?", (application_id,)
    ).fetchone()
    return row["posting_id"] if row is not None else None


def link_posting(conn: sqlite3.Connection, application_id: str, posting_id: str | None) -> None:
    """Tie an application to a collected posting (None unties it); both feed flags follow."""
    previous = _posting_of(conn, application_id)
    _touch(conn, application_id, posting_id=posting_id)
    _mirror(conn, previous)
    _mirror(conn, posting_id)


def update_application(conn: sqlite3.Connection, application_id: str, **columns: object) -> None:
    """Hand edits: note, title, location, company, dossier, applied_on (as ISO text)."""
    allowed = {"note", "title", "location", "company", "company_slug", "dossier", "applied_on"}
    unknown = set(columns) - allowed
    if unknown:
        raise ValueError(f"not editable here: {sorted(unknown)}")
    if "applied_on" in columns:
        columns["applied_on_estimated"] = 0
    _touch(conn, application_id, **columns)


def set_application_cv(
    conn: sqlite3.Connection,
    application_id: str,
    cv_id: str | None,
    source: CvSource = CvSource.CONFIRMED,
) -> None:
    """The CV sent, as a hand edit (None: unknown after all)."""
    _touch(
        conn,
        application_id,
        cv_id=cv_id,
        cv_source=source.value if cv_id is not None else None,
    )


def infer_application_cv(
    conn: sqlite3.Connection, application_id: str, cv_id: str, source: CvSource
) -> None:
    """The backfill's link: only on an application without a CV, and without moving
    `updated_at` — it is no hand edit, so the row stays the import's to refresh."""
    conn.execute(
        "UPDATE applications SET cv_id = ?, cv_source = ? "
        "WHERE application_id = ? AND cv_id IS NULL",
        (cv_id, source.value, application_id),
    )


def delete_application(conn: sqlite3.Connection, application_id: str) -> None:
    posting_id = _posting_of(conn, application_id)
    conn.execute("DELETE FROM applications WHERE application_id = ?", (application_id,))
    _mirror(conn, posting_id)


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
        cv_id=row["cv_id"],
        cv_source=CvSource(row["cv_source"]) if row["cv_source"] else None,
    )


def _select(conn: sqlite3.Connection, where: str, params: tuple[object, ...]) -> list[Application]:
    rows = conn.execute(
        f"SELECT * FROM applications {where} "
        "ORDER BY applied_on IS NULL, applied_on DESC, company, application_id",
        params,
    ).fetchall()
    events = _events(conn, [row["application_id"] for row in rows])
    return [_from_row(row, events[row["application_id"]]) for row in rows]


def list_applications(conn: sqlite3.Connection) -> list[Application]:
    """Every application, most recent first; undated ones last."""
    return _select(conn, "", ())


def get_application(conn: sqlite3.Connection, application_id: str) -> Application | None:
    found = _select(conn, "WHERE application_id = ?", (application_id,))
    return found[0] if found else None


def application_for_posting(conn: sqlite3.Connection, posting_id: str) -> Application | None:
    """The application the feed shows for this posting: the most recently updated one."""
    row = conn.execute(
        "SELECT application_id FROM applications WHERE posting_id = ? "
        "ORDER BY updated_at DESC, application_id DESC LIMIT 1",
        (posting_id,),
    ).fetchone()
    return get_application(conn, row["application_id"]) if row is not None else None


def match_application_ids(conn: sqlite3.Connection, prefix: str) -> list[str]:
    """Ids starting with `prefix` — the CLI takes a short prefix, like git takes a short sha."""
    rows = conn.execute(
        "SELECT application_id FROM applications WHERE application_id LIKE ? ESCAPE '\\' "
        "ORDER BY application_id",
        (prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",),
    ).fetchall()
    return [row["application_id"] for row in rows]
