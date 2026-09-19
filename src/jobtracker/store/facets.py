"""Facet counts under the current filter — blueprint/wp/WP02-store.md §3, invariant I6.

Each dimension is counted with every filter applied *except its own* — one
small indexed query per dimension, rather than one cross-aggregating query,
so ticking `country=GB` does not collapse every other country's count to
zero and lock the user out of also ticking `US`.
"""

import sqlite3

from pydantic import BaseModel

from jobtracker.store.postings import PostingFilter, filter_clauses, requires_active


class FacetCounts(BaseModel, frozen=True):
    countries: dict[str, int]
    cities: dict[str, int]
    companies: dict[str, int]
    sectors: dict[str, int]
    sources: dict[str, int]
    seniorities: dict[str, int]
    tech: dict[str, int]


def base_clauses(flt: PostingFilter) -> tuple[list[str], list[object]]:
    clauses = ["p.is_canonical = 1"]
    params: list[object] = []
    if requires_active(flt):
        clauses.append("p.is_active = 1")
    extra_clauses, extra_params = filter_clauses(flt)
    clauses.extend(extra_clauses)
    params.extend(extra_params)
    return clauses, params


def _count_dimension(
    conn: sqlite3.Connection,
    flt: PostingFilter,
    *,
    exclude_field: str,
    select: str,
    joins: str = "",
) -> dict[str, int]:
    amputated = flt.model_copy(update={exclude_field: frozenset()})
    clauses, params = base_clauses(amputated)
    sql = f"""
        SELECT {select} AS value, COUNT(DISTINCT p.posting_id) AS n
        FROM postings p
        JOIN companies c ON c.company_slug = p.company_slug
        LEFT JOIN user_flags uf ON uf.posting_id = p.posting_id
        {joins}
        WHERE {" AND ".join(clauses)} AND {select} IS NOT NULL
        GROUP BY {select}
    """
    return {row["value"]: row["n"] for row in conn.execute(sql, params).fetchall()}


def facet_counts(conn: sqlite3.Connection, flt: PostingFilter) -> FacetCounts:
    locations_join = "LEFT JOIN posting_locations pl ON pl.posting_id = p.posting_id"
    tech_join = "LEFT JOIN posting_tech pt ON pt.posting_id = p.posting_id"
    return FacetCounts(
        countries=_count_dimension(
            conn, flt, exclude_field="countries", select="pl.country", joins=locations_join
        ),
        cities=_count_dimension(
            conn, flt, exclude_field="cities", select="pl.city", joins=locations_join
        ),
        companies=_count_dimension(conn, flt, exclude_field="companies", select="p.company_slug"),
        sectors=_count_dimension(conn, flt, exclude_field="sectors", select="c.sector"),
        sources=_count_dimension(conn, flt, exclude_field="sources", select="p.source"),
        seniorities=_count_dimension(conn, flt, exclude_field="seniorities", select="p.seniority"),
        tech=_count_dimension(
            conn, flt, exclude_field="tech_any", select="pt.tech", joins=tech_join
        ),
    )
