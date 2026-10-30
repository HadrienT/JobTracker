-- CV versions — blueprint/wp/WP22-cvs.md.
--
-- A CV is identified by its content: `cv_id` is the SHA-256 of the file, stored once under
-- `data/career/cvs/<cv_id>.pdf` — the name a file carried says nothing (71 different folders
-- held a `CV_<Name>.pdf`, with a dozen different contents).
--
-- `pinned`: a version offered in the menus. A CV written for one offer stays out of them.
--
-- `cv_source` says how the link is known: `confirmed` by the user, or `inferred` (a default,
-- the dates of a CV's use). The response rate per version is only as good as this column.
-- Writing either column of `applications` from the backfill leaves `updated_at` alone: only a
-- hand edit protects a row from the import (store/applications.py).
CREATE TABLE IF NOT EXISTS cvs (
    cv_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    file_name TEXT NOT NULL,
    size INTEGER NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    created_at TEXT NOT NULL
);

ALTER TABLE applications ADD COLUMN cv_id TEXT REFERENCES cvs (cv_id);
ALTER TABLE applications ADD COLUMN cv_source TEXT CHECK (cv_source IN ('confirmed', 'inferred'));

CREATE INDEX IF NOT EXISTS idx_applications_cv ON applications (cv_id);
