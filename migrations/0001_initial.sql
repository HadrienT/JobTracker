-- Initial schema — blueprint/04-DATA-MODEL.md.
--
-- Applied by jobtracker.core.db.apply_migrations, which tracks applied
-- filenames itself (schema_migrations); every statement here is still
-- idempotent to a direct re-run, per blueprint/04-DATA-MODEL.md §5.

CREATE TABLE IF NOT EXISTS companies (
    company_slug TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    source TEXT NOT NULL,
    token TEXT NOT NULL,
    sector TEXT NOT NULL,
    hq_country TEXT NOT NULL,
    priority INTEGER NOT NULL,
    enabled INTEGER NOT NULL,
    last_ok_at TEXT,
    last_count INTEGER
);

CREATE TABLE IF NOT EXISTS postings (
    posting_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    is_canonical INTEGER NOT NULL,
    source TEXT NOT NULL,
    company_slug TEXT NOT NULL REFERENCES companies (company_slug),
    source_job_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    title_raw TEXT NOT NULL,
    -- Denormalized from `verdicts` (score, tier) so the feed's default sort
    -- can use a single index (blueprint/04-DATA-MODEL.md §4): SQLite has no
    -- cross-table index, and this pair is always written together with the
    -- posting by upsert_posting. `verdicts` stays the source of truth for
    -- the full MatchVerdict (reasons, rejection_reason, profile_version).
    score INTEGER,
    tier TEXT,
    role_family TEXT NOT NULL,
    seniority TEXT NOT NULL,
    min_years INTEGER,
    phd_required INTEGER NOT NULL,
    visa_sponsorship TEXT NOT NULL,
    visa_evidence TEXT,
    salary_min TEXT,
    salary_max TEXT,
    salary_currency TEXT,
    salary_period TEXT,
    posted_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    closes_at TEXT,
    content_hash TEXT NOT NULL,
    normalize_version INTEGER NOT NULL,
    is_active INTEGER NOT NULL,
    UNIQUE (source, company_slug, source_job_id)
);

CREATE TABLE IF NOT EXISTS posting_locations (
    posting_id TEXT NOT NULL REFERENCES postings (posting_id) ON DELETE CASCADE,
    city TEXT,
    country TEXT,
    region TEXT,
    remote_mode TEXT NOT NULL,
    raw TEXT
);

CREATE TABLE IF NOT EXISTS posting_tech (
    posting_id TEXT NOT NULL REFERENCES postings (posting_id) ON DELETE CASCADE,
    tech TEXT NOT NULL,
    PRIMARY KEY (posting_id, tech)
);

CREATE TABLE IF NOT EXISTS verdicts (
    posting_id TEXT PRIMARY KEY REFERENCES postings (posting_id) ON DELETE CASCADE,
    score INTEGER NOT NULL,
    tier TEXT NOT NULL,
    rejection_reason TEXT,
    reasons_json TEXT NOT NULL,
    profile_version INTEGER NOT NULL,
    scored_at TEXT NOT NULL,
    -- invariant I5 (blueprint/03-INTERFACES.md §2.4), enforced at the schema level
    CHECK ((tier = 'rejected') = (rejection_reason IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS posting_aliases (
    canonical_id TEXT NOT NULL REFERENCES postings (posting_id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    source_job_id TEXT NOT NULL,
    url TEXT NOT NULL,
    seen_at TEXT NOT NULL,
    UNIQUE (source, source_job_id)
);

CREATE TABLE IF NOT EXISTS raw_payloads (
    posting_id TEXT PRIMARY KEY REFERENCES postings (posting_id) ON DELETE CASCADE,
    payload_zstd BLOB NOT NULL,
    fetched_at TEXT NOT NULL
);

-- No single-column primary key: a run_id is shared by every log line of one
-- cycle (blueprint/04-DATA-MODEL.md §2), so several rows — aggregate and
-- per-company — can carry the same run_id.
CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    source TEXT NOT NULL,
    company_slug TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    fetched INTEGER NOT NULL,
    new INTEGER NOT NULL,
    updated INTEGER NOT NULL,
    aliased INTEGER NOT NULL,
    rejected INTEGER NOT NULL,
    requests_made INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_kind TEXT
);

-- The only table the API writes (blueprint/04-DATA-MODEL.md §2): kept apart
-- from `postings` so a rescoring pass can never clobber a favorite.
CREATE TABLE IF NOT EXISTS user_flags (
    posting_id TEXT PRIMARY KEY REFERENCES postings (posting_id) ON DELETE CASCADE,
    is_favorite INTEGER NOT NULL DEFAULT 0,
    is_hidden INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

-- Full-text search — blueprint/04-DATA-MODEL.md §3. `postings_fts` is an
-- "external content" FTS5 table backed by the ordinary table below, which is
-- what makes it possible to sync it with plain, well-documented AFTER
-- triggers instead of the FTS5 contentless-table 'delete' pseudo-command
-- (which needs the exact old column values in the *same* statement as the
-- new ones — awkward to get right across the several tables that feed it).
--
-- `description` has no column of its own on `postings` (it would be heavy,
-- never read by the feed, and re-read only in the detail view): it lives
-- only here, written once by store.search.index_description() when the
-- caller has the original RawPosting text in hand — upsert_posting's fixed
-- signature (blueprint/03-INTERFACES.md §3.5) does not carry it.
--
-- `remove_diacritics 2` is mandatory: the feed is multilingual, and
-- "Développeur" must be found by typing "developpeur".
CREATE TABLE IF NOT EXISTS posting_search_text (
    posting_id TEXT PRIMARY KEY REFERENCES postings (posting_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    company_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tech TEXT NOT NULL DEFAULT ''
);

CREATE VIRTUAL TABLE IF NOT EXISTS postings_fts USING fts5(
    title, company_name, description, tech,
    content='posting_search_text',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS posting_search_text_ai
AFTER INSERT ON posting_search_text
BEGIN
    INSERT INTO postings_fts (rowid, title, company_name, description, tech)
    VALUES (new.rowid, new.title, new.company_name, new.description, new.tech);
END;

CREATE TRIGGER IF NOT EXISTS posting_search_text_ad
AFTER DELETE ON posting_search_text
BEGIN
    INSERT INTO postings_fts (postings_fts, rowid, title, company_name, description, tech)
    VALUES ('delete', old.rowid, old.title, old.company_name, old.description, old.tech);
END;

CREATE TRIGGER IF NOT EXISTS posting_search_text_au
AFTER UPDATE ON posting_search_text
BEGIN
    INSERT INTO postings_fts (postings_fts, rowid, title, company_name, description, tech)
    VALUES ('delete', old.rowid, old.title, old.company_name, old.description, old.tech);
    INSERT INTO postings_fts (rowid, title, company_name, description, tech)
    VALUES (new.rowid, new.title, new.company_name, new.description, new.tech);
END;

-- Index — blueprint/04-DATA-MODEL.md §4. Every feed sort carries posting_id
-- as its second key: without that tie-breaker, two postings at the same
-- score make keyset pagination non-deterministic (skip or repeat a row),
-- a bug invisible in manual testing.
CREATE INDEX IF NOT EXISTS idx_postings_feed
    ON postings (is_canonical, is_active, tier, score DESC, posting_id DESC);

CREATE INDEX IF NOT EXISTS idx_postings_posted
    ON postings (is_canonical, is_active, posted_at DESC, posting_id DESC);

CREATE INDEX IF NOT EXISTS idx_postings_company ON postings (company_slug, is_active);
CREATE INDEX IF NOT EXISTS idx_postings_fingerprint ON postings (fingerprint);
CREATE INDEX IF NOT EXISTS idx_locations_country ON posting_locations (country, city);
CREATE INDEX IF NOT EXISTS idx_tech ON posting_tech (tech, posting_id);
CREATE INDEX IF NOT EXISTS idx_runs_source ON source_runs (source, started_at DESC);
