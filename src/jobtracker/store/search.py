"""Full-text search — blueprint/04-DATA-MODEL.md §3.

`postings_fts` is external-content on `posting_search_text` (migration
0001), kept in sync by plain SQL triggers for everything upsert_posting
already knows (title, company_name, tech). `index_description` is the one
piece triggers cannot provide: the full description text is not part of the
`Posting` DTO, so whichever caller holds the original `RawPosting` — today
only a test, eventually runtime — sets it explicitly once.
"""

import sqlite3


def index_description(conn: sqlite3.Connection, posting_id: str, description: str) -> None:
    conn.execute(
        "UPDATE posting_search_text SET description = ? WHERE posting_id = ?",
        (description, posting_id),
    )


def get_description(conn: sqlite3.Connection, posting_id: str) -> str | None:
    """The full description text for one posting — WP07's detail route."""
    row = conn.execute(
        "SELECT description FROM posting_search_text WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    return row["description"] if row is not None else None


def search_posting_ids(conn: sqlite3.Connection, query: str) -> set[str]:
    """Posting ids whose indexed text matches `query` (already diacritics-folded)."""
    rows = conn.execute(
        "SELECT posting_id FROM posting_search_text "
        "WHERE rowid IN (SELECT rowid FROM postings_fts WHERE postings_fts MATCH ?)",
        (query,),
    ).fetchall()
    return {row["posting_id"] for row in rows}
