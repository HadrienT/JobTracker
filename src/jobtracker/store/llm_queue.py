"""The deferred LLM queue — blueprint/wp/WP12-match-llm.md §4.1, migrations/0003.

Pure persistence: whether a posting *belongs* here (`match.prefilter`) and what
happens to it once dequeued (`runtime.residual`) are not this module's business.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class QueueEntry:
    posting_id: str
    queued_at: str
    attempts: int
    urgent: bool


def enqueue(conn: sqlite3.Connection, posting_id: str, *, urgent: bool, now: datetime) -> None:
    """Idempotent: a posting already waiting keeps its place and attempt count."""
    conn.execute(
        """
        INSERT INTO llm_queue (posting_id, queued_at, attempts, urgent) VALUES (?, ?, 0, ?)
        ON CONFLICT (posting_id) DO UPDATE SET urgent = MAX(urgent, excluded.urgent)
        """,
        (posting_id, now.isoformat(), int(urgent)),
    )


def pending(conn: sqlite3.Connection, limit: int) -> list[QueueEntry]:
    """Urgent first, then oldest first."""
    rows = conn.execute(
        "SELECT posting_id, queued_at, attempts, urgent FROM llm_queue "
        "ORDER BY urgent DESC, queued_at, posting_id LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        QueueEntry(
            posting_id=r["posting_id"],
            queued_at=r["queued_at"],
            attempts=r["attempts"],
            urgent=bool(r["urgent"]),
        )
        for r in rows
    ]


def record_skipped_attempt(conn: sqlite3.Connection, posting_id: str, *, now: datetime) -> None:
    conn.execute(
        "UPDATE llm_queue SET attempts = attempts + 1, last_attempt_at = ? WHERE posting_id = ?",
        (now.isoformat(), posting_id),
    )


def remove(conn: sqlite3.Connection, posting_id: str) -> None:
    conn.execute("DELETE FROM llm_queue WHERE posting_id = ?", (posting_id,))


def depth(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS n FROM llm_queue").fetchone()["n"])


def get_entry(conn: sqlite3.Connection, posting_id: str) -> QueueEntry | None:
    row = conn.execute(
        "SELECT posting_id, queued_at, attempts, urgent FROM llm_queue WHERE posting_id = ?",
        (posting_id,),
    ).fetchone()
    if row is None:
        return None
    return QueueEntry(
        posting_id=row["posting_id"],
        queued_at=row["queued_at"],
        attempts=row["attempts"],
        urgent=bool(row["urgent"]),
    )
