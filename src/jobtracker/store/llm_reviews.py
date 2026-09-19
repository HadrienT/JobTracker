"""What the local LLM has read, and what it changed — blueprint/wp/WP19-llm-review.md.

Two tables, one rule: a review belongs to the *content* it read. `content_hash` is stored with
every row, so a posting whose text changed since is simply unreviewed again, and a correction
made to old text never claims fields of the new one.
"""

import json
import sqlite3
from datetime import datetime
from typing import Any

from jobtracker.core.enums import ReviewOutcome
from jobtracker.core.models import FieldCorrection


class StoredCorrection(FieldCorrection, frozen=True):
    corrected_at: str


def record_review(
    conn: sqlite3.Connection,
    posting_id: str,
    *,
    content_hash: str,
    review_version: int,
    model: str,
    outcome: ReviewOutcome,
    confidence: float | None,
    now: datetime,
) -> None:
    conn.execute(
        """
        INSERT INTO llm_reviews (posting_id, content_hash, review_version, model, outcome,
                                 confidence, reviewed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (posting_id) DO UPDATE SET content_hash = excluded.content_hash,
            review_version = excluded.review_version, model = excluded.model,
            outcome = excluded.outcome, confidence = excluded.confidence,
            reviewed_at = excluded.reviewed_at
        """,
        (
            posting_id,
            content_hash,
            review_version,
            model,
            outcome.value,
            confidence,
            now.isoformat(),
        ),
    )


def record_corrections(
    conn: sqlite3.Connection,
    posting_id: str,
    corrections: list[FieldCorrection],
    *,
    content_hash: str,
    review_version: int,
    now: datetime,
) -> None:
    for correction in corrections:
        conn.execute(
            """
            INSERT INTO llm_corrections (posting_id, content_hash, field, before_json,
                                         after_json, evidence, confidence, review_version,
                                         corrected_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                posting_id,
                content_hash,
                correction.field,
                json.dumps(correction.before, sort_keys=True),
                json.dumps(correction.after, sort_keys=True),
                correction.evidence,
                correction.confidence,
                review_version,
                now.isoformat(),
            ),
        )


def list_corrections(
    conn: sqlite3.Connection, posting_id: str, *, content_hash: str
) -> list[StoredCorrection]:
    """The corrections that still apply to this posting's current content, oldest first."""
    rows = conn.execute(
        "SELECT * FROM llm_corrections WHERE posting_id = ? AND content_hash = ? "
        "ORDER BY correction_id",
        (posting_id, content_hash),
    ).fetchall()
    return [
        StoredCorrection(
            field=row["field"],
            before=json.loads(row["before_json"]),
            after=json.loads(row["after_json"]),
            evidence=row["evidence"],
            confidence=row["confidence"],
            corrected_at=row["corrected_at"],
        )
        for row in rows
    ]


def current_corrections(conn: sqlite3.Connection, posting_id: str) -> list[StoredCorrection]:
    """The corrections on the posting's current content — what the detail panel shows."""
    row = conn.execute(
        "SELECT content_hash FROM postings WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    if row is None:
        return []
    return list_corrections(conn, posting_id, content_hash=row["content_hash"])


def current_corrections_of_field(
    conn: sqlite3.Connection, field: str, *, posting_ids: list[str] | None = None
) -> list[tuple[str, list[StoredCorrection]]]:
    """`(posting_id, corrections)` for every posting whose current content carries this field's
    correction — the material of a revert."""
    rows = conn.execute(
        """
        SELECT DISTINCT c.posting_id FROM llm_corrections c
        JOIN postings p ON p.posting_id = c.posting_id AND p.content_hash = c.content_hash
        WHERE c.field = ?
        ORDER BY c.posting_id
        """,
        (field,),
    ).fetchall()
    wanted = {row["posting_id"] for row in rows}
    if posting_ids is not None:
        wanted &= set(posting_ids)
    return [
        (posting_id, [c for c in current_corrections(conn, posting_id) if c.field == field])
        for posting_id in sorted(wanted)
    ]


def forget_field(conn: sqlite3.Connection, posting_id: str, field: str) -> None:
    """Drop this field's corrections and the review row, so the posting is read again."""
    conn.execute(
        "DELETE FROM llm_corrections WHERE posting_id = ? AND field = ?", (posting_id, field)
    )
    conn.execute("DELETE FROM llm_reviews WHERE posting_id = ?", (posting_id,))


def corrected_fields(conn: sqlite3.Connection, posting_id: str) -> frozenset[str]:
    """Fields the LLM changed on the posting's *current* content: a replay must leave them alone."""
    rows = conn.execute(
        """
        SELECT DISTINCT c.field FROM llm_corrections c
        JOIN postings p ON p.posting_id = c.posting_id AND p.content_hash = c.content_hash
        WHERE c.posting_id = ?
        """,
        (posting_id,),
    ).fetchall()
    return frozenset(row["field"] for row in rows)


def unreviewed_posting_ids(
    conn: sqlite3.Connection, *, review_version: int, limit: int | None = None
) -> list[str]:
    """Active canonical postings with no current review, best score first.

    Best first, so an interrupted run has read the postings that matter most; rejected ones come
    last but are not skipped — a rejection is a verdict the reading may overturn.
    """
    sql = """
        SELECT p.posting_id FROM postings p
        LEFT JOIN llm_reviews r ON r.posting_id = p.posting_id
        WHERE p.is_active = 1 AND p.is_canonical = 1
          AND (r.posting_id IS NULL OR r.content_hash != p.content_hash
               OR r.review_version != ?)
        ORDER BY p.score DESC, p.posting_id
    """
    params: list[Any] = [review_version]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [row["posting_id"] for row in conn.execute(sql, params).fetchall()]


def count_reviews(conn: sqlite3.Connection, *, review_version: int) -> dict[str, int]:
    rows = conn.execute(
        "SELECT outcome, COUNT(*) AS n FROM llm_reviews WHERE review_version = ? GROUP BY outcome",
        (review_version,),
    ).fetchall()
    return {row["outcome"]: row["n"] for row in rows}
