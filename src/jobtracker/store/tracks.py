"""Track verdicts — blueprint/wp/WP20-tracks.md.

A track's verdict is derived data: it is recomputed from the stored posting whenever the quant
side rescored that posting since (`verdicts.scored_at` newer), the track's profile changed
(`profile_version`), or the posting entered the track's scope. Nothing here decides a score —
`match` does, `runtime.tracks` drives it.
"""

import json
import sqlite3
from collections.abc import Iterable

from jobtracker.core.enums import Tier, Track
from jobtracker.core.models import MatchVerdict, Reason


def _in_countries(countries: frozenset[str]) -> tuple[str, list[object]]:
    if not countries:
        return "1 = 1", []
    placeholders = ",".join("?" for _ in countries)
    params: list[object] = [*sorted(countries)]
    return (
        "EXISTS (SELECT 1 FROM posting_locations pl WHERE pl.posting_id = p.posting_id "
        f"AND pl.country IN ({placeholders}))",
        params,
    )


def stale_track_postings(
    conn: sqlite3.Connection, track: Track, *, profile_version: int, countries: frozenset[str]
) -> list[str]:
    """Canonical postings located in `countries` whose track verdict is missing or out of date."""
    scope_sql, scope_params = _in_countries(countries)
    rows = conn.execute(
        f"""
        SELECT p.posting_id FROM postings p
        JOIN verdicts v ON v.posting_id = p.posting_id
        LEFT JOIN track_verdicts t ON t.posting_id = p.posting_id AND t.track = ?
        WHERE p.is_canonical = 1 AND {scope_sql}
          AND (t.posting_id IS NULL OR t.profile_version != ? OR t.scored_at < v.scored_at)
        ORDER BY p.posting_id
        """,
        [track.value, *scope_params, profile_version],
    ).fetchall()
    return [row["posting_id"] for row in rows]


def drop_out_of_scope(conn: sqlite3.Connection, track: Track, *, countries: frozenset[str]) -> int:
    """Delete the track rows of postings that left its scope: moved, or became an alias."""
    scope_sql, scope_params = _in_countries(countries)
    cursor = conn.execute(
        f"""
        DELETE FROM track_verdicts WHERE track = ? AND posting_id NOT IN (
            SELECT p.posting_id FROM postings p WHERE p.is_canonical = 1 AND {scope_sql}
        )
        """,
        [track.value, *scope_params],
    )
    return cursor.rowcount


def drop_track_verdicts(conn: sqlite3.Connection, track: Track, posting_ids: Iterable[str]) -> None:
    conn.executemany(
        "DELETE FROM track_verdicts WHERE track = ? AND posting_id = ?",
        [(track.value, posting_id) for posting_id in posting_ids],
    )


def drop_unknown_tracks(conn: sqlite3.Connection, known: Iterable[Track]) -> int:
    """A track removed from configs/tracks.yaml takes its rows with it."""
    names = sorted(t.value for t in known)
    placeholders = ",".join("?" for _ in names) or "''"
    cursor = conn.execute(f"DELETE FROM track_verdicts WHERE track NOT IN ({placeholders})", names)
    return cursor.rowcount


def write_track_verdict(conn: sqlite3.Connection, track: Track, verdict: MatchVerdict) -> None:
    conn.execute(
        """
        INSERT INTO track_verdicts (
            track, posting_id, score, tier, rejection_reason, reasons_json, profile_version,
            scored_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (track, posting_id) DO UPDATE SET
            score = excluded.score, tier = excluded.tier,
            rejection_reason = excluded.rejection_reason, reasons_json = excluded.reasons_json,
            profile_version = excluded.profile_version, scored_at = excluded.scored_at
        """,
        (
            track.value,
            verdict.posting_id,
            verdict.score,
            verdict.tier.value,
            verdict.rejection_reason,
            json.dumps([r.model_dump(mode="json") for r in verdict.reasons]),
            verdict.profile_version,
            verdict.scored_at.isoformat(),
        ),
    )


def get_track_verdict(
    conn: sqlite3.Connection, track: Track, posting_id: str
) -> MatchVerdict | None:
    row = conn.execute(
        "SELECT * FROM track_verdicts WHERE track = ? AND posting_id = ?",
        (track.value, posting_id),
    ).fetchone()
    if row is None:
        return None
    return MatchVerdict(
        posting_id=posting_id,
        score=row["score"],
        tier=Tier(row["tier"]),
        reasons=tuple(Reason(**r) for r in json.loads(row["reasons_json"])),
        rejection_reason=row["rejection_reason"],
        profile_version=row["profile_version"],
        scored_at=row["scored_at"],
    )


def count_by_tier(conn: sqlite3.Connection, track: Track) -> dict[str, int]:
    rows = conn.execute(
        "SELECT tier, COUNT(*) AS n FROM track_verdicts WHERE track = ? GROUP BY tier",
        (track.value,),
    ).fetchall()
    return {row["tier"]: row["n"] for row in rows}
