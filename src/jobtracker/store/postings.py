"""Posting repository: upsert, dedup resolution, keyset pagination, favorites.

blueprint/03-INTERFACES.md §3.5 pins ``PostingFilter``, ``SortKey``, ``Page``
and this module's four public functions exactly; the API (WP07) imports
``PostingFilter`` from here rather than redefining it.
"""

import base64
import json
import sqlite3
from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel

from jobtracker.core.clock import utc_now
from jobtracker.core.enums import (
    AGGREGATOR_SOURCES,
    RemoteMode,
    RoleFamily,
    Seniority,
    Source,
    Tier,
    VisaStatus,
)
from jobtracker.core.errors import StorageError
from jobtracker.core.models import Compensation, Location, MatchVerdict, Posting, RawPosting


class PostingFilter(BaseModel, frozen=True):
    """The filtering contract, shared between the API and the store — one place only."""

    countries: frozenset[str] = frozenset()
    cities: frozenset[str] = frozenset()
    companies: frozenset[str] = frozenset()
    sectors: frozenset[str] = frozenset()
    sources: frozenset[Source] = frozenset()
    role_families: frozenset[RoleFamily] = frozenset()
    seniorities: frozenset[Seniority] = frozenset()
    remote_modes: frozenset[RemoteMode] = frozenset()
    tech_all: frozenset[str] = frozenset()
    tech_any: frozenset[str] = frozenset()
    visa: frozenset[VisaStatus] = frozenset()
    min_score: int = 0
    tiers: frozenset[Tier] = frozenset()
    posted_within_days: int | None = None
    query: str | None = None
    favorites_only: bool = False
    include_hidden: bool = False


class SortKey(StrEnum):
    SCORE = "score"
    POSTED = "posted"
    SEEN = "seen"
    COMPANY = "company"
    CLOSES = "closes"


class PostingRow(BaseModel, frozen=True):
    """One feed row — WP07 maps this to the API's ``PostingOut``."""

    posting_id: str
    company_slug: str
    company_name: str
    source: Source
    url: str
    title: str
    role_family: RoleFamily
    seniority: Seniority
    min_years: int | None
    phd_required: bool
    locations: tuple[Location, ...]
    compensation: Compensation
    visa_sponsorship: VisaStatus
    visa_evidence: str | None
    tech: frozenset[str]
    posted_at_raw: str | None
    first_seen_at_raw: str
    last_seen_at_raw: str
    closes_at_raw: str | None
    score: int
    tier: Tier
    is_favorite: bool
    is_hidden: bool


class Page(BaseModel, frozen=True):
    items: tuple[PostingRow, ...]
    next_cursor: str | None


# (SQL column expression, direction). Every entry gets `posting_id` appended
# as its tie-breaker in that same direction — blueprint/04-DATA-MODEL.md §4.
_SORT_COLUMNS: dict[SortKey, tuple[str, str]] = {
    SortKey.SCORE: ("p.score", "DESC"),
    SortKey.POSTED: ("p.posted_at", "DESC"),
    SortKey.SEEN: ("p.first_seen_at", "DESC"),
    SortKey.COMPANY: ("p.company_slug", "ASC"),
    SortKey.CLOSES: ("p.closes_at", "ASC"),
}


def _encode_cursor(sort_value: object, posting_id: str) -> str:
    payload = json.dumps([sort_value, posting_id])
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[object, str]:
    try:
        payload = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        value, posting_id = json.loads(payload)
        if not isinstance(posting_id, str):
            raise ValueError("cursor posting_id must be a string")
        return value, posting_id
    except Exception as exc:
        raise StorageError(f"invalid pagination cursor: {cursor!r}") from exc


def _keyset_predicate(
    column: str, direction: str, cursor_value: object, cursor_id: str
) -> tuple[str, list[object]]:
    """A NULLS-LAST-aware keyset predicate: 'rows strictly after (value, id)'."""
    op = "<" if direction == "DESC" else ">"
    if cursor_value is None:
        return f"({column} IS NULL AND p.posting_id {op} ?)", [cursor_id]
    sql = (
        f"(({column} IS NOT NULL AND ({column} {op} ? "
        f"OR ({column} = ? AND p.posting_id {op} ?))) OR {column} IS NULL)"
    )
    return sql, [cursor_value, cursor_value, cursor_id]


def _order_by(sort: SortKey) -> str:
    # NULLS LAST explicitly: SQLite defaults to NULLS FIRST on ASC (would put
    # every posting with no closes_at at the head of "closing soon" — the
    # exact inverse of what was asked, blueprint/wp/WP02-store.md §2). DESC
    # already defaults to NULLS LAST; spelling it out here too documents the
    # intent instead of relying on an implementation default.
    column, direction = _SORT_COLUMNS[sort]
    return f"{column} {direction} NULLS LAST, p.posting_id {direction}"


def filter_clauses(flt: PostingFilter) -> tuple[list[str], list[object]]:
    clauses: list[str] = []
    params: list[object] = []

    def _in(column: str, values: frozenset[str]) -> None:
        if not values:
            return
        placeholders = ",".join("?" for _ in values)
        clauses.append(f"{column} IN ({placeholders})")
        params.extend(sorted(values))

    if flt.countries:
        placeholders = ",".join("?" for _ in flt.countries)
        clauses.append(
            f"EXISTS (SELECT 1 FROM posting_locations pl WHERE pl.posting_id = p.posting_id "
            f"AND pl.country IN ({placeholders}))"
        )
        params.extend(sorted(flt.countries))
    if flt.cities:
        placeholders = ",".join("?" for _ in flt.cities)
        clauses.append(
            f"EXISTS (SELECT 1 FROM posting_locations pl WHERE pl.posting_id = p.posting_id "
            f"AND pl.city IN ({placeholders}))"
        )
        params.extend(sorted(flt.cities))
    if flt.remote_modes:
        placeholders = ",".join("?" for _ in flt.remote_modes)
        clauses.append(
            f"EXISTS (SELECT 1 FROM posting_locations pl WHERE pl.posting_id = p.posting_id "
            f"AND pl.remote_mode IN ({placeholders}))"
        )
        params.extend(sorted(v.value for v in flt.remote_modes))

    _in("p.company_slug", flt.companies)
    if flt.sectors:
        placeholders = ",".join("?" for _ in flt.sectors)
        clauses.append(f"c.sector IN ({placeholders})")
        params.extend(sorted(flt.sectors))
    _in("p.source", frozenset(v.value for v in flt.sources))
    _in("p.role_family", frozenset(v.value for v in flt.role_families))
    _in("p.seniority", frozenset(v.value for v in flt.seniorities))
    _in("p.visa_sponsorship", frozenset(v.value for v in flt.visa))
    _in("p.tier", frozenset(v.value for v in flt.tiers))

    if flt.tech_any:
        placeholders = ",".join("?" for _ in flt.tech_any)
        clauses.append(
            f"p.posting_id IN (SELECT posting_id FROM posting_tech WHERE tech IN ({placeholders}))"
        )
        params.extend(sorted(flt.tech_any))
    if flt.tech_all:
        placeholders = ",".join("?" for _ in flt.tech_all)
        clauses.append(
            "p.posting_id IN (SELECT posting_id FROM posting_tech "
            f"WHERE tech IN ({placeholders}) GROUP BY posting_id "
            f"HAVING COUNT(DISTINCT tech) = ?)"
        )
        params.extend(sorted(flt.tech_all))
        params.append(len(flt.tech_all))

    if flt.min_score:
        clauses.append("p.score >= ?")
        params.append(flt.min_score)

    if flt.posted_within_days is not None:
        clauses.append(
            "(CASE WHEN p.posted_at IS NOT NULL AND p.posted_at < p.first_seen_at "
            "THEN p.posted_at ELSE p.first_seen_at END) >= datetime(?, ?)"
        )
        params.extend([utc_now().isoformat(), f"-{flt.posted_within_days} days"])

    if flt.query:
        clauses.append(
            "p.posting_id IN (SELECT posting_id FROM posting_search_text "
            "WHERE rowid IN (SELECT rowid FROM postings_fts WHERE postings_fts MATCH ?))"
        )
        params.append(flt.query)

    if flt.favorites_only:
        clauses.append("uf.is_favorite = 1")
    if not flt.include_hidden:
        clauses.append("COALESCE(uf.is_hidden, 0) = 0")

    return clauses, params


def list_postings(
    conn: sqlite3.Connection, flt: PostingFilter, sort: SortKey, cursor: str | None, limit: int
) -> Page:
    """Keyset-paginated feed. Never uses OFFSET (ADR-007)."""
    clauses = ["p.is_canonical = 1"]
    params: list[object] = []
    if not flt.favorites_only:
        clauses.append("p.is_active = 1")

    extra_clauses, extra_params = filter_clauses(flt)
    clauses.extend(extra_clauses)
    params.extend(extra_params)

    column, direction = _SORT_COLUMNS[sort]
    if cursor is not None:
        cursor_value, cursor_id = _decode_cursor(cursor)
        predicate, predicate_params = _keyset_predicate(column, direction, cursor_value, cursor_id)
        clauses.append(predicate)
        params.extend(predicate_params)

    sql = f"""
        SELECT p.*, c.company_name AS company_name,
               COALESCE(uf.is_favorite, 0) AS is_favorite,
               COALESCE(uf.is_hidden, 0) AS is_hidden
        FROM postings p
        JOIN companies c ON c.company_slug = p.company_slug
        LEFT JOIN user_flags uf ON uf.posting_id = p.posting_id
        WHERE {" AND ".join(clauses)}
        ORDER BY {_order_by(sort)}
        LIMIT ?
    """
    rows = conn.execute(sql, [*params, limit + 1]).fetchall()

    items = [_row_to_posting_row(conn, row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = _encode_cursor(last[column.split(".")[-1]], last["posting_id"])
    return Page(items=tuple(items), next_cursor=next_cursor)


def _row_to_posting_row(conn: sqlite3.Connection, row: sqlite3.Row) -> PostingRow:
    locations = tuple(
        Location(
            city=loc["city"],
            country=loc["country"],
            region=loc["region"],
            remote_mode=RemoteMode(loc["remote_mode"]),
            raw=loc["raw"],
        )
        for loc in conn.execute(
            "SELECT city, country, region, remote_mode, raw FROM posting_locations "
            "WHERE posting_id = ?",
            (row["posting_id"],),
        ).fetchall()
    )
    tech = frozenset(
        r["tech"]
        for r in conn.execute(
            "SELECT tech FROM posting_tech WHERE posting_id = ?", (row["posting_id"],)
        ).fetchall()
    )
    compensation = Compensation(
        amount_min=Decimal(row["salary_min"]) if row["salary_min"] is not None else None,
        amount_max=Decimal(row["salary_max"]) if row["salary_max"] is not None else None,
        currency=row["salary_currency"],
        period=row["salary_period"],
        bonus_mentioned=False,
        equity_mentioned=False,
        raw=None,
    )
    return PostingRow(
        posting_id=row["posting_id"],
        company_slug=row["company_slug"],
        company_name=row["company_name"],
        source=Source(row["source"]),
        url=row["url"],
        title=row["title"],
        role_family=RoleFamily(row["role_family"]),
        seniority=Seniority(row["seniority"]),
        min_years=row["min_years"],
        phd_required=bool(row["phd_required"]),
        locations=locations,
        compensation=compensation,
        visa_sponsorship=VisaStatus(row["visa_sponsorship"]),
        visa_evidence=row["visa_evidence"],
        tech=tech,
        posted_at_raw=row["posted_at"],
        first_seen_at_raw=row["first_seen_at"],
        last_seen_at_raw=row["last_seen_at"],
        closes_at_raw=row["closes_at"],
        score=row["score"],
        tier=Tier(row["tier"]),
        is_favorite=bool(row["is_favorite"]),
        is_hidden=bool(row["is_hidden"]),
    )


def _existing_by_identity(conn: sqlite3.Connection, posting: Posting) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT posting_id, content_hash FROM postings "
        "WHERE source = ? AND company_slug = ? AND source_job_id = ?",
        (posting.source.value, posting.company_slug, posting.source_job_id),
    ).fetchone()
    return row


def _canonical_by_fingerprint(conn: sqlite3.Connection, fingerprint: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT posting_id, source FROM postings WHERE fingerprint = ? AND is_canonical = 1",
        (fingerprint,),
    ).fetchone()
    return row


def _write_posting_row(
    conn: sqlite3.Connection, posting: Posting, verdict: MatchVerdict, *, is_canonical: bool
) -> None:
    conn.execute(
        """
        INSERT INTO postings (
            posting_id, fingerprint, is_canonical, source, company_slug, source_job_id, url,
            title, title_raw, score, tier, role_family, seniority, min_years, phd_required,
            visa_sponsorship, visa_evidence, salary_min, salary_max, salary_currency,
            salary_period, posted_at, first_seen_at, last_seen_at, closes_at, content_hash,
            normalize_version, is_active
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT (posting_id) DO UPDATE SET
            fingerprint = excluded.fingerprint, is_canonical = excluded.is_canonical,
            source = excluded.source, company_slug = excluded.company_slug,
            source_job_id = excluded.source_job_id, url = excluded.url, title = excluded.title,
            title_raw = excluded.title_raw, score = excluded.score, tier = excluded.tier,
            role_family = excluded.role_family, seniority = excluded.seniority,
            min_years = excluded.min_years, phd_required = excluded.phd_required,
            visa_sponsorship = excluded.visa_sponsorship, visa_evidence = excluded.visa_evidence,
            salary_min = excluded.salary_min, salary_max = excluded.salary_max,
            salary_currency = excluded.salary_currency, salary_period = excluded.salary_period,
            posted_at = excluded.posted_at, first_seen_at = excluded.first_seen_at,
            last_seen_at = excluded.last_seen_at, closes_at = excluded.closes_at,
            content_hash = excluded.content_hash, normalize_version = excluded.normalize_version,
            is_active = excluded.is_active
        """,
        (
            posting.posting_id,
            posting.fingerprint,
            int(is_canonical),
            posting.source.value,
            posting.company_slug,
            posting.source_job_id,
            posting.url,
            posting.title,
            posting.title_raw,
            verdict.score,
            verdict.tier.value,
            posting.role_family.value,
            posting.seniority.value,
            posting.min_years,
            int(posting.phd_required),
            posting.visa_sponsorship.value,
            posting.visa_evidence,
            str(posting.compensation.amount_min)
            if posting.compensation.amount_min is not None
            else None,
            str(posting.compensation.amount_max)
            if posting.compensation.amount_max is not None
            else None,
            posting.compensation.currency,
            posting.compensation.period.value if posting.compensation.period else None,
            posting.posted_at.isoformat() if posting.posted_at else None,
            posting.first_seen_at.isoformat(),
            posting.last_seen_at.isoformat(),
            posting.closes_at.isoformat() if posting.closes_at else None,
            posting.content_hash,
            posting.normalize_version,
            1,
        ),
    )
    conn.execute("DELETE FROM posting_locations WHERE posting_id = ?", (posting.posting_id,))
    conn.executemany(
        "INSERT INTO posting_locations (posting_id, city, country, region, remote_mode, raw) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (posting.posting_id, loc.city, loc.country, loc.region, loc.remote_mode.value, loc.raw)
            for loc in posting.locations
        ],
    )
    conn.execute("DELETE FROM posting_tech WHERE posting_id = ?", (posting.posting_id,))
    conn.executemany(
        "INSERT INTO posting_tech (posting_id, tech) VALUES (?, ?)",
        [(posting.posting_id, tech) for tech in sorted(posting.tech)],
    )
    conn.execute(
        """
        INSERT INTO verdicts (
            posting_id, score, tier, rejection_reason, reasons_json, profile_version, scored_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (posting_id) DO UPDATE SET
            score = excluded.score, tier = excluded.tier,
            rejection_reason = excluded.rejection_reason, reasons_json = excluded.reasons_json,
            profile_version = excluded.profile_version, scored_at = excluded.scored_at
        """,
        (
            posting.posting_id,
            verdict.score,
            verdict.tier.value,
            verdict.rejection_reason,
            json.dumps([r.model_dump(mode="json") for r in verdict.reasons]),
            verdict.profile_version,
            verdict.scored_at.isoformat(),
        ),
    )
    company_name_row = conn.execute(
        "SELECT company_name FROM companies WHERE company_slug = ?", (posting.company_slug,)
    ).fetchone()
    company_name = company_name_row["company_name"] if company_name_row else posting.company_slug
    conn.execute(
        """
        INSERT INTO posting_search_text (posting_id, title, company_name, tech)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (posting_id) DO UPDATE SET
            title = excluded.title, company_name = excluded.company_name, tech = excluded.tech
        """,
        (posting.posting_id, posting.title, company_name, " ".join(sorted(posting.tech))),
    )


def upsert_posting(conn: sqlite3.Connection, posting: Posting, verdict: MatchVerdict) -> str:
    """Insert or refresh a posting, resolving fingerprint collisions.

    blueprint/wp/WP02-store.md §4, three branches:
    1. Unknown fingerprint -> new canonical posting.
    2. Known fingerprint, existing canonical is an ATS and the new one is an
       aggregator -> the new one becomes an alias, no posting row is created.
    3. Known fingerprint, existing canonical is an aggregator and the new one
       is an ATS -> the ATS posting takes over as canonical; the old one is
       demoted to an alias and its favorites/hidden flag follow the new id.
    """
    existing = _existing_by_identity(conn, posting)
    if existing is not None:
        if existing["content_hash"] == posting.content_hash:
            # Same content already stored: touch freshness only, never rescore
            # (blueprint/wp/WP02-store.md §4) — `scored_at` stays untouched.
            conn.execute(
                "UPDATE postings SET last_seen_at = ? WHERE posting_id = ?",
                (posting.last_seen_at.isoformat(), existing["posting_id"]),
            )
            return str(existing["posting_id"])
        _write_posting_row(
            conn,
            posting.model_copy(update={"posting_id": existing["posting_id"]}),
            verdict,
            is_canonical=True,
        )
        return str(existing["posting_id"])

    canonical = _canonical_by_fingerprint(conn, posting.fingerprint)
    if canonical is None:
        _write_posting_row(conn, posting, verdict, is_canonical=True)
        return posting.posting_id

    existing_is_aggregator = Source(canonical["source"]) in AGGREGATOR_SOURCES
    new_is_aggregator = posting.source in AGGREGATOR_SOURCES

    if not existing_is_aggregator:
        # Case 2 (also covers two ATS sources sharing a fingerprint: the
        # older one — already canonical — stays canonical, per §4's "cas
        # réel : une société qui migre d'ATS").
        record_alias(
            conn,
            str(canonical["posting_id"]),
            RawPosting(
                source=posting.source,
                company_slug=posting.company_slug,
                source_job_id=posting.source_job_id,
                url=posting.url,
                title_raw=posting.title_raw,
                description_raw="",
                location_raw=None,
                department_raw=None,
                posted_at_raw=None,
                payload=b"",
                fetched_at=posting.last_seen_at,
                content_hash=posting.content_hash,
            ),
        )
        return str(canonical["posting_id"])

    if not new_is_aggregator:
        # Case 3: takeover. The old canonical row is demoted and its
        # (source, source_job_id) becomes an alias of the new one.
        old_id = str(canonical["posting_id"])
        old_row = conn.execute(
            "SELECT source, source_job_id, url, last_seen_at FROM postings WHERE posting_id = ?",
            (old_id,),
        ).fetchone()
        _write_posting_row(conn, posting, verdict, is_canonical=True)
        conn.execute("UPDATE postings SET is_canonical = 0 WHERE posting_id = ?", (old_id,))
        conn.execute(
            """
            INSERT INTO posting_aliases (canonical_id, source, source_job_id, url, seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (source, source_job_id) DO UPDATE SET
                canonical_id = excluded.canonical_id, seen_at = excluded.seen_at
            """,
            (
                posting.posting_id,
                old_row["source"],
                old_row["source_job_id"],
                old_row["url"],
                old_row["last_seen_at"],
            ),
        )
        moved = conn.execute(
            "UPDATE user_flags SET posting_id = ? WHERE posting_id = ? "
            "AND NOT EXISTS (SELECT 1 FROM user_flags WHERE posting_id = ?)",
            (posting.posting_id, old_id, posting.posting_id),
        )
        if moved.rowcount == 0:
            conn.execute("DELETE FROM user_flags WHERE posting_id = ?", (old_id,))
        return posting.posting_id

    # Both aggregators sharing a fingerprint: keep the existing one canonical.
    record_alias(
        conn,
        str(canonical["posting_id"]),
        RawPosting(
            source=posting.source,
            company_slug=posting.company_slug,
            source_job_id=posting.source_job_id,
            url=posting.url,
            title_raw=posting.title_raw,
            description_raw="",
            location_raw=None,
            department_raw=None,
            posted_at_raw=None,
            payload=b"",
            fetched_at=posting.last_seen_at,
            content_hash=posting.content_hash,
        ),
    )
    return str(canonical["posting_id"])


def record_alias(conn: sqlite3.Connection, canonical_id: str, alias: RawPosting) -> None:
    """Record a republication of `canonical_id` without creating a new posting."""
    conn.execute(
        """
        INSERT INTO posting_aliases (canonical_id, source, source_job_id, url, seen_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (source, source_job_id) DO UPDATE SET
            canonical_id = excluded.canonical_id, url = excluded.url, seen_at = excluded.seen_at
        """,
        (
            canonical_id,
            alias.source.value,
            alias.source_job_id,
            alias.url,
            alias.fetched_at.isoformat(),
        ),
    )


def mark_favorite(conn: sqlite3.Connection, posting_id: str, value: bool) -> None:
    conn.execute(
        """
        INSERT INTO user_flags (posting_id, is_favorite, is_hidden, updated_at)
        VALUES (?, ?, 0, ?)
        ON CONFLICT (posting_id) DO UPDATE SET is_favorite = excluded.is_favorite,
            updated_at = excluded.updated_at
        """,
        (posting_id, int(value), utc_now().isoformat()),
    )


def mark_hidden(conn: sqlite3.Connection, posting_id: str, value: bool) -> None:
    conn.execute(
        """
        INSERT INTO user_flags (posting_id, is_favorite, is_hidden, updated_at)
        VALUES (?, 0, ?, ?)
        ON CONFLICT (posting_id) DO UPDATE SET is_hidden = excluded.is_hidden,
            updated_at = excluded.updated_at
        """,
        (posting_id, int(value), utc_now().isoformat()),
    )


__all__: Sequence[str] = (
    "Page",
    "PostingFilter",
    "PostingRow",
    "SortKey",
    "list_postings",
    "mark_favorite",
    "mark_hidden",
    "record_alias",
    "upsert_posting",
)
