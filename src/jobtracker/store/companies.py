"""Materialized registry repository — blueprint/04-DATA-MODEL.md §2 `companies`.

`configs/companies.yaml` stays the source of truth for everything but
`last_ok_at`/`last_count`, which only a real collection run produces (the
P3 counter, blueprint/00-PRIMER.md §2). `sync_companies` replaces the whole
table from the config-derived list on every startup, keeping the two health
columns for slugs that still exist.
"""

import sqlite3
from collections.abc import Iterable

from jobtracker.core.enums import Source
from jobtracker.core.models import Board, Company


def sync_companies(conn: sqlite3.Connection, boards: Iterable[Board]) -> None:
    """Replace the registry with `boards`, preserving existing health counters."""
    boards = list(boards)
    for board in boards:
        conn.execute(
            """
            INSERT INTO companies (
                company_slug, company_name, source, token, sector, hq_country, priority, enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (company_slug) DO UPDATE SET
                company_name = excluded.company_name, source = excluded.source,
                token = excluded.token, sector = excluded.sector, hq_country = excluded.hq_country,
                priority = excluded.priority, enabled = excluded.enabled, discovered = 0
            """,
            (
                board.company_slug,
                board.company_name,
                board.source.value,
                board.token,
                board.sector,
                board.hq_country,
                board.priority,
                int(board.enabled),
            ),
        )
    slugs = {b.company_slug for b in boards}
    if slugs:
        placeholders = ",".join("?" for _ in slugs)
        conn.execute(
            f"DELETE FROM companies WHERE discovered = 0 AND company_slug NOT IN ({placeholders})",
            tuple(slugs),
        )
    else:
        conn.execute("DELETE FROM companies WHERE discovered = 0")


def ensure_discovered_company(
    conn: sqlite3.Connection, *, slug: str, name: str, source: Source, hq_country: str
) -> None:
    """A `companies` row for an aggregator-only employer — never overwrites a registry row."""
    conn.execute(
        """
        INSERT OR IGNORE INTO companies (
            company_slug, company_name, source, token, sector, hq_country, priority, enabled,
            discovered
        ) VALUES (?, ?, ?, '', 'unknown', ?, 3, 0, 1)
        """,
        (slug, name, source.value, hq_country),
    )


def list_discovered(conn: sqlite3.Connection) -> list[tuple[str, str, int]]:
    """(slug, name, active postings) for every employer known only through an aggregator."""
    rows = conn.execute(
        """
        SELECT c.company_slug, c.company_name, COUNT(p.posting_id) AS n
        FROM companies c LEFT JOIN postings p
            ON p.company_slug = c.company_slug AND p.is_active = 1
        WHERE c.discovered = 1
        GROUP BY c.company_slug, c.company_name
        ORDER BY n DESC, c.company_name
        """
    ).fetchall()
    return [(r["company_slug"], r["company_name"], r["n"]) for r in rows]


def record_run_result(
    conn: sqlite3.Connection, company_slug: str, *, ok_at: str, count: int
) -> None:
    """Update the P3 counter after a completed collection run for one company."""
    conn.execute(
        "UPDATE companies SET last_ok_at = ?, last_count = ? WHERE company_slug = ?",
        (ok_at, count, company_slug),
    )


def get_company(conn: sqlite3.Connection, company_slug: str) -> Company | None:
    row = conn.execute("SELECT * FROM companies WHERE company_slug = ?", (company_slug,)).fetchone()
    return _row_to_company(row) if row is not None else None


def list_companies(
    conn: sqlite3.Connection,
    *,
    sector: str | None = None,
    country: str | None = None,
    include_discovered: bool = False,
) -> list[Company]:
    clauses = [] if include_discovered else ["discovered = 0"]
    params: list[object] = []
    if sector is not None:
        clauses.append("sector = ?")
        params.append(sector)
    if country is not None:
        clauses.append("hq_country = ?")
        params.append(country)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"SELECT * FROM companies {where} ORDER BY company_slug", params).fetchall()
    return [_row_to_company(row) for row in rows]


def _row_to_company(row: sqlite3.Row) -> Company:
    return Company(
        company_slug=row["company_slug"],
        company_name=row["company_name"],
        source=Source(row["source"]),
        token=row["token"],
        sector=row["sector"],
        hq_country=row["hq_country"],
        priority=row["priority"],
        enabled=bool(row["enabled"]),
        last_ok_at=row["last_ok_at"],
        last_count=row["last_count"],
        discovered=bool(row["discovered"]),
    )
