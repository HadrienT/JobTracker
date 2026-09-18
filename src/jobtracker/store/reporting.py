"""The aggregate queries behind the weekly report — blueprint/wp/WP16-feedback.md §3-4.

Read-only, and only aggregation: what to *say* about the numbers is
`runtime.report`'s job. Weeks are ISO-style `%Y-%W` buckets of `first_seen_at`, so
each cohort's resolution rate reflects the normalizer version that processed it —
which is what makes an improvement visible as an evolution over four weeks.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

_RESOLVED_PREDICATES = {
    "seniority": "p.seniority != 'unknown'",
    "visa": "p.visa_sponsorship != 'unknown'",
    "role": "p.role_family != 'other'",
    "location": (
        "EXISTS (SELECT 1 FROM posting_locations l "
        "WHERE l.posting_id = p.posting_id AND l.country IS NOT NULL)"
    ),
    "tech": "EXISTS (SELECT 1 FROM posting_tech t WHERE t.posting_id = p.posting_id)",
    "compensation": "p.salary_min IS NOT NULL",
}


@dataclass(frozen=True)
class WeeklyResolution:
    week: str
    postings: int
    rates: dict[str, float]


@dataclass(frozen=True)
class FavoriteRow:
    posting_id: str
    title: str
    company_slug: str
    score: int
    tier: str
    rejection_reason: str | None


@dataclass(frozen=True)
class Lift:
    key: str
    favorites: int
    favorite_share: float
    base_share: float

    @property
    def lift(self) -> float:
        return self.favorite_share / self.base_share if self.base_share else 0.0


def coverage(conn: sqlite3.Connection) -> tuple[int, dict[str, int], dict[str, int]]:
    """(companies with an active posting, active postings by sector, by country)."""
    companies = conn.execute(
        "SELECT COUNT(DISTINCT company_slug) AS n FROM postings WHERE is_active = 1 "
        "AND is_canonical = 1"
    ).fetchone()["n"]
    by_sector = {
        r["sector"]: r["n"]
        for r in conn.execute(
            "SELECT c.sector AS sector, COUNT(*) AS n FROM postings p "
            "JOIN companies c ON c.company_slug = p.company_slug "
            "WHERE p.is_active = 1 AND p.is_canonical = 1 GROUP BY c.sector ORDER BY n DESC"
        )
    }
    by_country = {
        r["country"]: r["n"]
        for r in conn.execute(
            "SELECT l.country AS country, COUNT(DISTINCT p.posting_id) AS n FROM postings p "
            "JOIN posting_locations l ON l.posting_id = p.posting_id "
            "WHERE p.is_active = 1 AND p.is_canonical = 1 AND l.country IS NOT NULL "
            "GROUP BY l.country ORDER BY n DESC"
        )
    }
    return companies, by_sector, by_country


def silent_companies(conn: sqlite3.Connection, *, now: datetime, days: int = 30) -> list[str]:
    """Enabled registry companies with no posting seen for `days` — most likely a broken token."""
    cutoff = (now - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        SELECT c.company_slug FROM companies c
        WHERE c.enabled = 1 AND c.discovered = 0 AND NOT EXISTS (
            SELECT 1 FROM postings p WHERE p.company_slug = c.company_slug
              AND p.is_active = 1 AND p.last_seen_at >= ?
        ) ORDER BY c.company_slug
        """,
        (cutoff,),
    ).fetchall()
    return [r["company_slug"] for r in rows]


def weekly_resolution(
    conn: sqlite3.Connection, *, now: datetime, weeks: int = 4
) -> list[WeeklyResolution]:
    """Resolution rate per stage for each of the last `weeks` first-seen cohorts."""
    result = []
    for offset in range(weeks - 1, -1, -1):
        start = now - timedelta(days=7 * (offset + 1))
        end = now - timedelta(days=7 * offset)
        selects = ", ".join(
            f"AVG(CASE WHEN {predicate} THEN 1.0 ELSE 0.0 END) AS {name}"
            for name, predicate in _RESOLVED_PREDICATES.items()
        )
        row = conn.execute(
            f"SELECT COUNT(*) AS n, {selects} FROM postings p "
            "WHERE p.is_canonical = 1 AND p.first_seen_at >= ? AND p.first_seen_at < ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        result.append(
            WeeklyResolution(
                week=f"{start.date()}…{end.date()}",
                postings=row["n"],
                rates={n: (row[n] or 0.0) for n in _RESOLVED_PREDICATES},
            )
        )
    return result


def tiers_by_week(
    conn: sqlite3.Connection, *, now: datetime, weeks: int = 4
) -> list[tuple[str, dict[str, int]]]:
    out = []
    for offset in range(weeks - 1, -1, -1):
        start = now - timedelta(days=7 * (offset + 1))
        end = now - timedelta(days=7 * offset)
        counts = {
            r["tier"]: r["n"]
            for r in conn.execute(
                "SELECT tier, COUNT(*) AS n FROM postings WHERE is_canonical = 1 "
                "AND first_seen_at >= ? AND first_seen_at < ? GROUP BY tier",
                (start.isoformat(), end.isoformat()),
            )
        }
        out.append((f"{start.date()}…{end.date()}", counts))
    return out


def rejection_reasons(conn: sqlite3.Connection, *, limit: int = 10) -> list[tuple[str, int]]:
    rows = conn.execute(
        "SELECT v.rejection_reason AS reason, COUNT(*) AS n FROM verdicts v "
        "JOIN postings p ON p.posting_id = v.posting_id "
        "WHERE p.is_canonical = 1 AND v.rejection_reason IS NOT NULL "
        "GROUP BY v.rejection_reason ORDER BY n DESC, reason LIMIT ?",
        (limit,),
    ).fetchall()
    return [(r["reason"], r["n"]) for r in rows]


def llm_load(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """(resolved by the LLM, still queued, skipped turns so far)."""
    resolved = conn.execute(
        "SELECT COUNT(*) AS n FROM postings WHERE resolver_stage = 'llm'"
    ).fetchone()["n"]
    queue = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(attempts), 0) AS skipped FROM llm_queue"
    ).fetchone()
    return resolved, queue["n"], queue["skipped"]


def favorites(conn: sqlite3.Connection) -> list[FavoriteRow]:
    rows = conn.execute(
        """
        SELECT p.posting_id, p.title, p.company_slug, v.score, v.tier, v.rejection_reason
        FROM user_flags f
        JOIN postings p ON p.posting_id = f.posting_id
        JOIN verdicts v ON v.posting_id = p.posting_id
        WHERE f.is_favorite = 1 ORDER BY v.score DESC, p.posting_id
        """
    ).fetchall()
    return [
        FavoriteRow(
            r["posting_id"],
            r["title"],
            r["company_slug"],
            r["score"],
            r["tier"],
            r["rejection_reason"],
        )
        for r in rows
    ]


def _lifts(favorite_counts: dict[str, int], base_counts: dict[str, int]) -> list[Lift]:
    fav_total = sum(favorite_counts.values())
    base_total = sum(base_counts.values())
    if not fav_total or not base_total:
        return []
    lifts = [
        Lift(key, n, n / fav_total, base_counts.get(key, 0) / base_total)
        for key, n in favorite_counts.items()
        if base_counts.get(key)
    ]
    return sorted(lifts, key=lambda x: (-x.lift, x.key))


def favorite_lifts(conn: sqlite3.Connection) -> tuple[list[Lift], list[Lift]]:
    """Companies and tech over-represented among favorites relative to the active feed."""

    def counts(sql: str) -> dict[str, int]:
        return {r[0]: r[1] for r in conn.execute(sql)}

    fav_company = counts(
        "SELECT p.company_slug, COUNT(*) FROM user_flags f JOIN postings p "
        "ON p.posting_id = f.posting_id WHERE f.is_favorite = 1 GROUP BY p.company_slug"
    )
    base_company = counts(
        "SELECT company_slug, COUNT(*) FROM postings WHERE is_active = 1 AND is_canonical = 1 "
        "GROUP BY company_slug"
    )
    fav_tech = counts(
        "SELECT t.tech, COUNT(*) FROM user_flags f JOIN posting_tech t "
        "ON t.posting_id = f.posting_id WHERE f.is_favorite = 1 GROUP BY t.tech"
    )
    base_tech = counts(
        "SELECT t.tech, COUNT(*) FROM posting_tech t "
        "JOIN postings p ON p.posting_id = t.posting_id "
        "WHERE p.is_active = 1 AND p.is_canonical = 1 GROUP BY t.tech"
    )
    return _lifts(fav_company, base_company), _lifts(fav_tech, base_tech)
