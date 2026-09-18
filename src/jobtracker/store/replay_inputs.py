"""What a replay reads — blueprint/wp/WP16-feedback.md §2. Read-only: never a collection.

`normalize()` takes a `RawPosting`. This module rebuilds exactly that from what
was archived at ingestion, so the replay measures the normalizer against the same
input it originally saw — without a network call and without needing each ATS
collector's payload mapper.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReplayInput:
    posting_id: str
    source: str
    company_slug: str
    source_job_id: str
    url: str
    title_raw: str
    description: str
    location_raw: str | None
    posted_at_raw: str | None
    content_hash: str
    first_seen_at: str
    hq_country: str | None
    normalize_version: int


def list_replay_inputs(
    conn: sqlite3.Connection,
    *,
    since: datetime | None = None,
    normalize_version_below: int | None = None,
) -> list[ReplayInput]:
    clauses = ["p.is_canonical = 1"]
    params: list[object] = []
    if since is not None:
        clauses.append("p.first_seen_at >= ?")
        params.append(since.isoformat())
    if normalize_version_below is not None:
        clauses.append("p.normalize_version < ?")
        params.append(normalize_version_below)
    rows = conn.execute(
        f"""
        SELECT p.posting_id, p.source, p.company_slug, p.source_job_id, p.url, p.title_raw,
               p.location_raw, p.posted_at_raw, p.posted_at, p.content_hash, p.first_seen_at,
               p.normalize_version, COALESCE(s.description, '') AS description,
               c.hq_country AS hq_country,
               (SELECT group_concat(raw, ' / ') FROM posting_locations pl
                 WHERE pl.posting_id = p.posting_id AND pl.raw IS NOT NULL) AS parsed_locations
        FROM postings p
        LEFT JOIN posting_search_text s ON s.posting_id = p.posting_id
        LEFT JOIN companies c ON c.company_slug = p.company_slug
        WHERE {" AND ".join(clauses)}
        ORDER BY p.first_seen_at, p.posting_id
        """,
        params,
    ).fetchall()
    return [
        ReplayInput(
            posting_id=r["posting_id"],
            source=r["source"],
            company_slug=r["company_slug"],
            source_job_id=r["source_job_id"],
            url=r["url"],
            title_raw=r["title_raw"],
            description=r["description"],
            # Pre-0005 rows: the parsed parts are the best available stand-in.
            location_raw=r["location_raw"]
            if r["location_raw"] is not None
            else r["parsed_locations"],
            posted_at_raw=r["posted_at_raw"] if r["posted_at_raw"] is not None else r["posted_at"],
            content_hash=r["content_hash"],
            first_seen_at=r["first_seen_at"],
            hq_country=r["hq_country"] or None,
            normalize_version=r["normalize_version"],
        )
        for r in rows
    ]
