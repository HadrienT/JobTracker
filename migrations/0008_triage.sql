-- Triage — the user's own "no" / "maybe" on a posting.
--
-- Lives in `user_flags` for the same reason the favorite and the application status do: it
-- is the user's data, never the pipeline's. A triaged posting leaves the main feed and is
-- read back from its own list (`GET /postings?triage=no|maybe`), where the tag can be
-- changed or cleared — unlike `is_hidden`, which has no list to come back from.
--
-- NULL means "not triaged yet". The set of values is `core.enums.Triage`.
ALTER TABLE user_flags ADD COLUMN triage TEXT
    CHECK (triage IS NULL OR triage IN ('no', 'maybe'));
