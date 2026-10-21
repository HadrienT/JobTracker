-- Applications — blueprint/wp/WP21-applications.md.
--
-- One row = one application sent for one job, whether or not the collector ever saw the
-- posting. Most of the history predates JobTracker (a spreadsheet and a folder of screenshots),
-- so `posting_id` is optional and the company is kept as the user wrote it; `company_slug` is
-- the registry entry when the name resolves to one.
--
-- The user's data, never the pipeline's: nothing derived from a posting is copied here, and a
-- posting purged by retention only loses its link (`ON DELETE SET NULL`), never the row.
--
-- Dates are ISO `YYYY-MM-DD` (days, not instants: the sheet records no time). The files of an
-- application (offer screenshots, the CV sent) live under `data/career/applications/<dossier>`.
CREATE TABLE IF NOT EXISTS applications (
    application_id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    company_slug TEXT,
    title TEXT,
    location TEXT,
    applied_on TEXT,
    -- 1 when `applied_on` was read off the files' timestamps, not written down by the user
    applied_on_estimated INTEGER NOT NULL DEFAULT 0 CHECK (applied_on_estimated IN (0, 1)),
    closed_on TEXT,
    status TEXT NOT NULL CHECK (status IN
        ('applied', 'interview', 'offer', 'rejected', 'withdrawn')),
    -- the user's own words for the outcome ("Failed 2nd interview", "Job filled"), kept verbatim
    reason TEXT NOT NULL DEFAULT '',
    posting_id TEXT REFERENCES postings (posting_id) ON DELETE SET NULL,
    dossier TEXT,
    origin TEXT NOT NULL CHECK (origin IN ('import', 'feed', 'cli')),
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_applications_applied ON applications (applied_on DESC);
CREATE INDEX IF NOT EXISTS idx_applications_posting ON applications (posting_id);
CREATE INDEX IF NOT EXISTS idx_applications_company ON applications (company_slug);

-- The status history WP18 lacked (§5): one row per change, the latest one wins on
-- `applications.status`. `on_date` is the day it happened, as far as anyone knows.
CREATE TABLE IF NOT EXISTS application_events (
    application_id TEXT NOT NULL REFERENCES applications (application_id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    on_date TEXT,
    status TEXT NOT NULL CHECK (status IN
        ('applied', 'interview', 'offer', 'rejected', 'withdrawn')),
    reason TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (application_id, seq)
);
