-- Application tracking — blueprint/wp/WP18-tracking.md.
--
-- Lives in `user_flags`, next to the favorite and hidden flags, for the same reason: it is
-- the user's data, not the pipeline's, so a rescoring or a replay can never clobber it, and a
-- posting that carries a row is exempt from the retention purge (a posting you applied to must
-- survive the offer closing — that is exactly when you want to look it up).
--
-- `application_status` NULL means "not tracked". The set of values is `ApplicationStatus`;
-- the CHECK keeps a typo from ever reaching the table.
ALTER TABLE user_flags ADD COLUMN application_status TEXT
    CHECK (application_status IS NULL OR application_status IN
        ('applied', 'interview', 'offer', 'rejected', 'withdrawn'));
ALTER TABLE user_flags ADD COLUMN status_updated_at TEXT;
ALTER TABLE user_flags ADD COLUMN note TEXT NOT NULL DEFAULT '';
