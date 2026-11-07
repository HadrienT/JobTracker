"""Purge policy — blueprint/04-DATA-MODEL.md §6.

Deleting a `raw_payloads` row never cascades onto `postings` (the foreign key
runs the other way): a purge only ever removes what it names, by
construction, never the offer itself. `user_flags` and `applications` are
never purged here, and neither is a posting either of them points at: a
favorite, a hide or an application outlives the offer closing on its board.

The purge ends by compacting the full-text index. `postings_fts` is rewritten
through triggers on every update of a posting's search text, and FTS5 only
merges the resulting segments lazily: left alone, the index grew to twice the
size of the text it indexes (543 MB for 283 MB of descriptions, 2026-11-07).
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

DEFAULT_RAW_PAYLOAD_RETENTION_DAYS = 365
DEFAULT_REJECTED_NOT_QUANT_RETENTION_DAYS = 90
DEFAULT_INACTIVE_POSTING_RETENTION_DAYS = 180
DEFAULT_SOURCE_RUN_RETENTION_DAYS = 90

# What the user touched is never purged. `user_flags.posting_id` cascades from `postings`:
# deleting a flagged posting would erase its favorite, hide or note (WP16 §5).
# `applications.posting_id` is set to NULL instead: the application would survive but lose
# the offer it answered, its text and its link (WP21). Either one exempts the posting.
_KEPT_BY_USER = (
    "posting_id NOT IN (SELECT posting_id FROM user_flags) "
    "AND posting_id NOT IN (SELECT posting_id FROM applications WHERE posting_id IS NOT NULL)"
)


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
    """Drop postings inactive past `retention_days` (cascades to their child rows).

    `raw_payloads` no longer has a foreign key to `postings` (migration 0002:
    a payload must survive a normalizer crash on a posting row that may never
    exist), so the cascade above never touches it — the orphan sweep below
    does, bounding how long an unreachable payload lingers past whatever is
    left of its own retention window.
    """
    cutoff = (now - timedelta(days=retention_days)).isoformat()
    cursor = conn.execute(
        f"DELETE FROM postings WHERE is_active = 0 AND last_seen_at < ? AND {_KEPT_BY_USER}",
        (cutoff,),
    )
    removed = cursor.rowcount
    conn.execute(
        "DELETE FROM raw_payloads WHERE posting_id NOT IN (SELECT posting_id FROM postings)"
    )
    return removed


def purge_source_runs(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    retention_days: int = DEFAULT_SOURCE_RUN_RETENTION_DAYS,
) -> int:
    cutoff = (now - timedelta(days=retention_days)).isoformat()
    cursor = conn.execute("DELETE FROM source_runs WHERE started_at < ?", (cutoff,))
    return cursor.rowcount


# A purge on a WAL database holds the single write lock for as long as its
# transaction is open (blueprint/wp/WP16-feedback.md §5): one giant DELETE would
# make the API's favorite writes wait on `busy_timeout`. So each purge deletes a
# bounded batch and commits, releasing the lock between batches.
DEFAULT_BATCH_SIZE = 500


@dataclass(frozen=True)
class RetentionResult:
    raw_payloads: int
    inactive_postings: int
    source_runs: int


def _delete_in_batches(
    conn: sqlite3.Connection,
    select_ids_sql: str,
    delete_sql: str,
    params: dict[str, object],
    *,
    batch_size: int,
    on_batch: Callable[[], None] | None,
) -> int:
    total = 0
    while True:
        ids = [
            r[0]
            for r in conn.execute(
                f"{select_ids_sql} LIMIT :batch_size", {**params, "batch_size": batch_size}
            ).fetchall()
        ]
        if not ids:
            return total
        placeholders = ",".join("?" for _ in ids)
        conn.execute(delete_sql.format(placeholders=placeholders), ids)
        conn.commit()  # the lock is released here, before the next batch
        total += len(ids)
        if on_batch is not None:
            on_batch()


def run_retention(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_batch: Callable[[], None] | None = None,
) -> RetentionResult:
    """The daily purge, in bounded batches. Never touches `user_flags`.

    `on_batch` runs after each commit — a test hook, and the natural place to
    yield if this ever shares a process with a collection cycle.
    """
    cutoff_payload = (now - timedelta(days=DEFAULT_RAW_PAYLOAD_RETENTION_DAYS)).isoformat()
    cutoff_rejected = (now - timedelta(days=DEFAULT_REJECTED_NOT_QUANT_RETENTION_DAYS)).isoformat()
    payloads = _delete_in_batches(
        conn,
        """
        SELECT rp.posting_id FROM raw_payloads rp
        LEFT JOIN verdicts v ON v.posting_id = rp.posting_id
        WHERE (v.rejection_reason = 'not_quant' AND rp.fetched_at < :cutoff_rejected)
           OR (COALESCE(v.rejection_reason, '') != 'not_quant' AND rp.fetched_at < :cutoff_default)
        """,
        "DELETE FROM raw_payloads WHERE posting_id IN ({placeholders})",
        {"cutoff_rejected": cutoff_rejected, "cutoff_default": cutoff_payload},
        batch_size=batch_size,
        on_batch=on_batch,
    )
    cutoff_inactive = (now - timedelta(days=DEFAULT_INACTIVE_POSTING_RETENTION_DAYS)).isoformat()
    postings = _delete_in_batches(
        conn,
        f"SELECT posting_id FROM postings WHERE is_active = 0 AND last_seen_at < :cutoff "
        f"AND {_KEPT_BY_USER}",
        "DELETE FROM postings WHERE posting_id IN ({placeholders})",
        {"cutoff": cutoff_inactive},
        batch_size=batch_size,
        on_batch=on_batch,
    )
    _delete_in_batches(  # the orphan sweep purge_inactive_postings documents
        conn,
        "SELECT posting_id FROM raw_payloads "
        "WHERE posting_id NOT IN (SELECT posting_id FROM postings)",
        "DELETE FROM raw_payloads WHERE posting_id IN ({placeholders})",
        {},
        batch_size=batch_size,
        on_batch=on_batch,
    )
    cutoff_runs = (now - timedelta(days=DEFAULT_SOURCE_RUN_RETENTION_DAYS)).isoformat()
    runs = _delete_in_batches(
        conn,
        "SELECT id FROM source_runs WHERE started_at < :cutoff",
        "DELETE FROM source_runs WHERE id IN ({placeholders})",
        {"cutoff": cutoff_runs},
        batch_size=batch_size,
        on_batch=on_batch,
    )
    optimize_search_index(conn)
    return RetentionResult(raw_payloads=payloads, inactive_postings=postings, source_runs=runs)


def optimize_search_index(conn: sqlite3.Connection) -> None:
    """Merge every FTS5 segment into one and drop the deleted entries they still hold.

    One write transaction of a few seconds on ~100k postings; readers keep reading (WAL).
    The freed pages are reused by later writes, and backups (`VACUUM INTO`) skip them.
    """
    conn.execute("INSERT INTO postings_fts (postings_fts) VALUES ('optimize')")
    conn.commit()
