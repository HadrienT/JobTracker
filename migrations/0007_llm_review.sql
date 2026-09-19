-- The whole-feed LLM re-read — blueprint/wp/WP19-llm-review.md.
--
-- `llm_reviews`: which postings the local LLM has read, and what it concluded. A review is
-- current only for the content it read (`content_hash`) and the prompt/schema it read it with
-- (`review_version`): a re-fetch that changes the content, or a bumped version, queues the
-- posting again. `outcome` says whether the reading changed anything, confirmed the stored
-- values, or was set aside (under-confident / non-conforming): "read" and "changed" are not
-- the same fact, and a review that changes nothing must still not be repeated.
--
-- `llm_corrections`: every field the LLM changed, with the value before, the value after and the
-- verbatim quote that justified it. This is what lets a correction be audited and undone, and it
-- is how a replay knows which fields are the LLM's (see runtime/replay.py).
CREATE TABLE IF NOT EXISTS llm_reviews (
    posting_id TEXT PRIMARY KEY REFERENCES postings (posting_id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    review_version INTEGER NOT NULL,
    model TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('corrected', 'confirmed', 'set_aside')),
    confidence REAL,
    reviewed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_corrections (
    correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id TEXT NOT NULL REFERENCES postings (posting_id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    field TEXT NOT NULL,
    before_json TEXT NOT NULL,
    after_json TEXT NOT NULL,
    evidence TEXT,
    confidence REAL NOT NULL,
    review_version INTEGER NOT NULL,
    corrected_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_corrections_posting ON llm_corrections (posting_id);
