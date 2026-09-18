-- raw_payloads no longer requires its posting to already exist.
--
-- blueprint/wp/WP08-runtime.md §2: the pipeline archives a payload BEFORE
-- normalizing it, precisely so a normalizer crash on an exotic posting still
-- leaves the payload recoverable for a later replay. The posting row for
-- that id does not exist yet at that moment — and if the posting turns out
-- to be unparseable garbage, it may never exist — so the payload can no
-- longer be tied by a foreign key to a `postings` row that might not be
-- there. SQLite has no ALTER TABLE to drop a constraint in place, hence the
-- table-replacement pattern (blueprint/04-DATA-MODEL.md §5).
--
-- `raw_payloads` already has its own independent, age-based retention
-- (store.retention.purge_raw_payloads); losing the ON DELETE CASCADE from
-- `postings` only means a purged posting's payload now waits out its own
-- retention window instead of disappearing immediately — store.retention's
-- purge_inactive_postings also does an explicit orphan sweep to bound that.

CREATE TABLE IF NOT EXISTS raw_payloads_new (
    posting_id TEXT PRIMARY KEY,
    payload_zstd BLOB NOT NULL,
    fetched_at TEXT NOT NULL
);

INSERT INTO raw_payloads_new (posting_id, payload_zstd, fetched_at)
SELECT posting_id, payload_zstd, fetched_at FROM raw_payloads;

DROP TABLE raw_payloads;

ALTER TABLE raw_payloads_new RENAME TO raw_payloads;
