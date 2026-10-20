"""The track pass — blueprint/wp/WP20-tracks.md.

A track's verdicts are derived from postings already stored and normalized: this pass finds
the ones in a track's scope whose verdict is missing or out of date, scores them against the
track's profile, and drops the rows of postings that left the scope. It runs after every
collection and after the LLM has corrected postings, and is cheap when nothing changed — one
query per track.
"""

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from jobtracker.core.enums import Tier, Track
from jobtracker.core.logging import get_logger
from jobtracker.match.profile import Profile
from jobtracker.match.rules import in_scope
from jobtracker.match.score import evaluate
from jobtracker.store.postings import get_posting
from jobtracker.store.tracks import (
    count_by_tier,
    drop_out_of_scope,
    drop_track_verdicts,
    drop_unknown_tracks,
    stale_track_postings,
    write_track_verdict,
)

_logger = get_logger(__name__)

_COMMIT_EVERY = 500


@dataclass(frozen=True)
class TrackPass:
    track: Track
    scored: int
    dropped: int
    tiers: Mapping[str, int]


def score_tracks(
    conn: sqlite3.Connection, profiles: Mapping[Track, Profile]
) -> tuple[TrackPass, ...]:
    removed = drop_unknown_tracks(conn, profiles.keys())
    if removed:
        _logger.info("tracks_unknown_dropped", rows=removed)
    conn.commit()
    return tuple(_score_track(conn, track, profile) for track, profile in profiles.items())


def _score_track(conn: sqlite3.Connection, track: Track, profile: Profile) -> TrackPass:
    countries = profile.scope.countries
    dropped = drop_out_of_scope(conn, track, countries=countries)
    left_scope: list[str] = []
    scored = 0
    for posting_id in stale_track_postings(
        conn, track, profile_version=profile.version, countries=countries
    ):
        posting = get_posting(conn, posting_id)
        # The SQL above only looks at countries; `in_scope` is the rule itself.
        if posting is None or not in_scope(posting, profile=profile):
            left_scope.append(posting_id)
            continue
        write_track_verdict(conn, track, evaluate(posting, profile=profile))
        scored += 1
        if scored % _COMMIT_EVERY == 0:
            conn.commit()
    drop_track_verdicts(conn, track, left_scope)
    conn.commit()

    tiers = count_by_tier(conn, track)
    _logger.info(
        "track_scored",
        track=track.value,
        scored=scored,
        dropped=dropped + len(left_scope),
        tiers=tiers,
    )
    # A track nobody's postings reach is a silent failure (CLAUDE.md): a registry gone quiet,
    # a country code the geo index never produces. Loud, not empty.
    shown = sum(n for tier, n in tiers.items() if tier != Tier.REJECTED.value)
    if shown == 0:
        _logger.warning("track_empty", track=track.value, rows=sum(tiers.values()))
    return TrackPass(track=track, scored=scored, dropped=dropped + len(left_scope), tiers=tiers)
