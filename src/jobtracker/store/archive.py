"""Raw payload archive — blueprint/04-DATA-MODEL.md §2 `raw_payloads`.

Never skipped (blueprint/00-PRIMER.md §2 interdit n°10): without the original
payload, no normalizer improvement is measurable by replay (WP16).
"""

import sqlite3
from datetime import datetime

from jobtracker.core.payloads import pack, unpack


def archive_payload(
    conn: sqlite3.Connection, posting_id: str, payload: bytes, fetched_at: datetime
) -> None:
    conn.execute(
        """
        INSERT INTO raw_payloads (posting_id, payload_zstd, fetched_at) VALUES (?, ?, ?)
        ON CONFLICT (posting_id) DO UPDATE SET
            payload_zstd = excluded.payload_zstd, fetched_at = excluded.fetched_at
        """,
        (posting_id, pack(payload), fetched_at.isoformat()),
    )


def read_payload(conn: sqlite3.Connection, posting_id: str) -> bytes | None:
    row = conn.execute(
        "SELECT payload_zstd FROM raw_payloads WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    return unpack(row["payload_zstd"]) if row is not None else None


def has_payload(conn: sqlite3.Connection, posting_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM raw_payloads WHERE posting_id = ?", (posting_id,)).fetchone()
    return row is not None
