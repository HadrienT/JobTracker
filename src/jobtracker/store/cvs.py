"""The CV registry — blueprint/wp/WP22-cvs.md.

Which CVs exist, under what name. Which application used which is on `applications`
(`store.applications.set_application_cv`).
"""

import sqlite3
from datetime import datetime

from jobtracker.core.models import Cv

_SELECT = """
    SELECT c.*, COUNT(a.application_id) AS applications
    FROM cvs c LEFT JOIN applications a ON a.cv_id = c.cv_id
"""


def add_cv(
    conn: sqlite3.Connection,
    cv_id: str,
    *,
    label: str,
    file_name: str,
    size: int,
    pinned: bool,
    created_at: datetime,
) -> None:
    """Record a CV. One already known keeps its name; asking for a version pins it."""
    conn.execute(
        """
        INSERT INTO cvs (cv_id, label, file_name, size, pinned, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (cv_id) DO UPDATE SET pinned = MAX(cvs.pinned, excluded.pinned)
        """,
        (cv_id, label, file_name, size, int(pinned), created_at.isoformat()),
    )


def _from_row(row: sqlite3.Row) -> Cv:
    return Cv(
        cv_id=row["cv_id"],
        label=row["label"],
        file_name=row["file_name"],
        size=row["size"],
        pinned=bool(row["pinned"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        applications=row["applications"],
    )


def list_cvs(conn: sqlite3.Connection) -> list[Cv]:
    """Every CV, newest first."""
    rows = conn.execute(
        f"{_SELECT} GROUP BY c.cv_id ORDER BY c.created_at DESC, c.cv_id"
    ).fetchall()
    return [_from_row(row) for row in rows]


def get_cv(conn: sqlite3.Connection, cv_id: str) -> Cv | None:
    row = conn.execute(f"{_SELECT} WHERE c.cv_id = ? GROUP BY c.cv_id", (cv_id,)).fetchone()
    return _from_row(row) if row is not None else None


def edit_cv(
    conn: sqlite3.Connection,
    cv_id: str,
    *,
    label: str | None = None,
    pinned: bool | None = None,
) -> None:
    """Only what is given changes."""
    if label is not None:
        conn.execute("UPDATE cvs SET label = ? WHERE cv_id = ?", (label, cv_id))
    if pinned is not None:
        conn.execute("UPDATE cvs SET pinned = ? WHERE cv_id = ?", (int(pinned), cv_id))


def current_cv_id(conn: sqlite3.Connection) -> str | None:
    """The version to assume for a new application: the pinned one last sent — or added, since
    a version just added is the one about to be sent. A CV written for one offer is never
    assumed for the next."""
    row = conn.execute(
        """
        SELECT c.cv_id FROM cvs c LEFT JOIN applications a ON a.cv_id = c.cv_id
        WHERE c.pinned = 1
        GROUP BY c.cv_id
        ORDER BY MAX(COALESCE(MAX(a.applied_on), ''), c.created_at) DESC, c.cv_id
        LIMIT 1
        """
    ).fetchone()
    return row["cv_id"] if row is not None else None


def match_cv_ids(conn: sqlite3.Connection, prefix: str) -> list[str]:
    """Ids starting with `prefix` — the CLI takes a short prefix, like git takes a short sha."""
    rows = conn.execute(
        "SELECT cv_id FROM cvs WHERE cv_id LIKE ? ORDER BY cv_id",
        (prefix.lower().replace("%", "").replace("_", "") + "%",),
    ).fetchall()
    return [row["cv_id"] for row in rows]
