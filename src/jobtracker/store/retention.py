"""Purge policy — blueprint/04-DATA-MODEL.md §6.

Deleting a `raw_payloads` row never cascades onto `postings` (the foreign key
runs the other way): a purge only ever removes what it names, by
construction, never the offer itself. `user_flags` is never purged here —
that table has no retention window at all; a favorite survives the posting
that earned it disappearing from the board.
"""

import sqlite3
from datetime import datetime, timedelta

DEFAULT_RAW_PAYLOAD_RETENTION_DAYS = 365
DEFAULT_REJECTED_NOT_QUANT_RETENTION_DAYS = 90
DEFAULT_INACTIVE_POSTING_RETENTION_DAYS = 180
DEFAULT_SOURCE_RUN_RETENTION_DAYS = 90


def purge_raw_payloads(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    retention_days: int = DEFAULT_RAW_PAYLOAD_RETENTION_DAYS,
    rejected_not_quant_retention_days: int = DEFAULT_REJECTED_NOT_QUANT_RETENTION_DAYS,
) -> int:
    """Delete payloads past retention; `not_quant` rejects get a shorter window."""
    cutoff_default = (now - timedelta(days=retention_days)).isoformat()
    cutoff_rejected = (now - timedelta(days=rejected_not_quant_retention_days)).isoformat()
    cursor = conn.execute(
        """
        DELETE FROM raw_payloads WHERE posting_id IN (
            SELECT rp.posting_id FROM raw_payloads rp
            LEFT JOIN verdicts v ON v.posting_id = rp.posting_id
            WHERE
                (v.rejection_reason = 'not_quant' AND rp.fetched_at < :cutoff_rejected)
                OR (
                    COALESCE(v.rejection_reason, '') != 'not_quant'
                    AND rp.fetched_at < :cutoff_default
                )
        )
        """,
        {"cutoff_rejected": cutoff_rejected, "cutoff_default": cutoff_default},
    )
    return cursor.rowcount


def purge_inactive_postings(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    retention_days: int = DEFAULT_INACTIVE_POSTING_RETENTION_DAYS,
) -> int:
    """Drop postings inactive past `retention_days` (cascades to their child rows)."""
    cutoff = (now - timedelta(days=retention_days)).isoformat()
    cursor = conn.execute(
        "DELETE FROM postings WHERE is_active = 0 AND last_seen_at < ?", (cutoff,)
    )
    return cursor.rowcount


def purge_source_runs(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    retention_days: int = DEFAULT_SOURCE_RUN_RETENTION_DAYS,
) -> int:
    cutoff = (now - timedelta(days=retention_days)).isoformat()
    cursor = conn.execute("DELETE FROM source_runs WHERE started_at < ?", (cutoff,))
    return cursor.rowcount
