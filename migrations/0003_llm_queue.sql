-- The deferred LLM lane — blueprint/wp/WP12-match-llm.md §4.1.
--
-- `llama-server` is shared with OpenHands and is not always up: an ambiguous
-- posting waits here until a drain finds the server free, instead of being
-- lost or retried in a loop. `attempts` counts turns skipped because the
-- server was busy or down — it is observability, never a give-up threshold
-- (ADR-010: no remote fallback, and a skipped turn costs thirty minutes).
--
-- `postings.resolver_stage` persists which stage last settled the fields the
-- score is computed from ("rules" | "llm"), so a posting the LLM already
-- resolved is never queued again.

ALTER TABLE postings ADD COLUMN resolver_stage TEXT NOT NULL DEFAULT 'rules';

CREATE TABLE IF NOT EXISTS llm_queue (
    posting_id TEXT PRIMARY KEY REFERENCES postings (posting_id) ON DELETE CASCADE,
    queued_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    urgent INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_llm_queue_order ON llm_queue (urgent DESC, queued_at);
