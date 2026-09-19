"""What the map tab draws: one count per located `(country, city)` — blueprint/wp/WP17-map.md.

A posting can carry several locations, so it can sit under several pins; each pin counts a
posting once (`COUNT(DISTINCT ...)`), and `placed` counts it once across all of them. The
location filters (`countries`, `cities`, `remote_modes`) are applied to the pinned *row* as
well as to the posting: filtering on `countries=US` must not leave a pin in London just
because the same posting is also open in New York.
"""

import sqlite3

from pydantic import BaseModel

from jobtracker.store.facets import base_clauses
from jobtracker.store.postings import PostingFilter


class LocationCount(BaseModel, frozen=True):
    country: str
    city: str
    count: int
    # The posting itself when the pin holds exactly one — the front opens it without a round trip.
    sample_posting_id: str


class MapCounts(BaseModel, frozen=True):
    locations: tuple[LocationCount, ...]
    total: int  # postings matching the filter, located or not
    placed: int  # of those, postings that appear under at least one pin


_FROM = """
    FROM postings p
    JOIN companies c ON c.company_slug = p.company_slug
    LEFT JOIN user_flags uf ON uf.posting_id = p.posting_id
"""


def _location_row_clauses(flt: PostingFilter) -> tuple[list[str], list[object]]:
    clauses = ["pl.city IS NOT NULL"]
    params: list[object] = []
    if flt.countries:
        clauses.append(f"pl.country IN ({','.join('?' for _ in flt.countries)})")
        params.extend(sorted(flt.countries))
    if flt.cities:
        clauses.append(f"pl.city IN ({','.join('?' for _ in flt.cities)})")
        params.extend(sorted(flt.cities))
    if flt.remote_modes:
        clauses.append(f"pl.remote_mode IN ({','.join('?' for _ in flt.remote_modes)})")
        params.extend(sorted(mode.value for mode in flt.remote_modes))
    return clauses, params


def location_counts(conn: sqlite3.Connection, flt: PostingFilter) -> MapCounts:
    base, base_params = base_clauses(flt)
    row_clauses, row_params = _location_row_clauses(flt)
    where = " AND ".join([*base, *row_clauses])
    params = [*base_params, *row_params]
    join = "JOIN posting_locations pl ON pl.posting_id = p.posting_id"

    rows = conn.execute(
        f"""
        SELECT pl.country AS country, pl.city AS city,
               COUNT(DISTINCT p.posting_id) AS n, MIN(p.posting_id) AS sample
        {_FROM} {join}
        WHERE {where}
        GROUP BY pl.country, pl.city
        ORDER BY n DESC, pl.country, pl.city
        """,
        params,
    ).fetchall()
    placed = conn.execute(
        f"SELECT COUNT(DISTINCT p.posting_id) {_FROM} {join} WHERE {where}", params
    ).fetchone()[0]
    total = conn.execute(
        f"SELECT COUNT(DISTINCT p.posting_id) {_FROM} WHERE {' AND '.join(base)}", base_params
    ).fetchone()[0]

    return MapCounts(
        locations=tuple(
            LocationCount(
                country=row["country"],
                city=row["city"],
                count=row["n"],
                sample_posting_id=row["sample"],
            )
            for row in rows
        ),
        total=total,
        placed=placed,
    )
