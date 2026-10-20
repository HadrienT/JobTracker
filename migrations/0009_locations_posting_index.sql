-- posting_locations had no index leading with `posting_id`.
--
-- Every read that starts from a posting and fetches its locations — the row hydration of
-- `list_postings`, and the country/city facets, which LEFT JOIN this table — scanned the
-- whole table once per posting. Invisible on the inbox (about a thousand postings), it
-- makes `/facets` take minutes on the rejected tier (tens of thousands).
CREATE INDEX idx_locations_posting ON posting_locations (posting_id);
