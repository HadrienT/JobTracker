-- A cycle in which no board was due asked nothing, yet was recorded as `empty`: with one
-- weekly board in its family, a healthy source looked mute. Those runs are `skipped`.
UPDATE source_runs SET status = 'skipped'
WHERE company_slug IS NULL AND status = 'empty' AND requests_made = 0 AND fetched = 0;
