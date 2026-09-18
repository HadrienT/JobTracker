-- Employers seen at an aggregator but absent from configs/companies.yaml.
--
-- blueprint/wp/WP13-aggregators.md §4: the real value of an aggregator is to
-- surface employers the registry doesn't know yet. `postings.company_slug` has
-- a foreign key to `companies`, and `sync_companies` rebuilds the table from the
-- YAML on every startup — so an unknown employer needs a row that is (1) legal
-- as a foreign-key target and (2) never swept away by that rebuild. `discovered`
-- is that marker, and the WP00 discovery report is simply `WHERE discovered = 1`.

ALTER TABLE companies ADD COLUMN discovered INTEGER NOT NULL DEFAULT 0;
