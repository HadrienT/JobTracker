-- The normalizer's raw inputs, kept exactly — blueprint/wp/WP16-feedback.md §2.
--
-- `normalize()` consumes a RawPosting. Its description is already archived
-- verbatim (posting_search_text.description) and its title in `title_raw`; what
-- was lost is the *unparsed* location string and posting date — the location
-- column only keeps each parsed part. Without them a replay of the location and
-- date stages would measure a reconstruction, not the real input. Rows ingested
-- before this migration have NULL here and fall back to the parsed parts.

ALTER TABLE postings ADD COLUMN location_raw TEXT;
ALTER TABLE postings ADD COLUMN posted_at_raw TEXT;
