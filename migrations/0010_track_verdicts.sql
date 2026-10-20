-- Track verdicts — blueprint/wp/WP20-tracks.md.
--
-- A track is a second search scored against its own profile (configs/tracks.yaml), shown in
-- its own tab. The quant feed keeps `verdicts` and the denormalized `postings.score/tier`;
-- a track writes here instead, one row per posting *in its scope* — a posting outside the
-- track's countries has no row at all, rather than a rejection.
--
-- `scored_at` is compared with `verdicts.scored_at`: whenever the quant side rescores a
-- posting (new content, an LLM correction, a replay) the track row is older and gets redone.
CREATE TABLE IF NOT EXISTS track_verdicts (
    track TEXT NOT NULL,
    posting_id TEXT NOT NULL REFERENCES postings (posting_id) ON DELETE CASCADE,
    score INTEGER NOT NULL,
    tier TEXT NOT NULL,
    rejection_reason TEXT,
    reasons_json TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    scored_at TEXT NOT NULL,
    PRIMARY KEY (track, posting_id),
    -- invariant I5, as on `verdicts`
    CHECK ((tier = 'rejected') = (rejection_reason IS NOT NULL))
);

-- The track feed's default sort, as idx_postings_feed is the quant feed's.
CREATE INDEX IF NOT EXISTS idx_track_verdicts_feed
    ON track_verdicts (track, tier, score DESC, posting_id DESC);
CREATE INDEX IF NOT EXISTS idx_track_verdicts_posting ON track_verdicts (posting_id);
