#!/usr/bin/env python3
"""Build the frozen demo database the e2e suite runs against.

blueprint/wp/WP14-quality.md §2.3: the e2e journey needs a database whose content
never changes between runs, or its assertions ("the first row after sorting by date")
would rot. The postings are the hand-labeled golden corpus pushed through the *real*
ingest path — normalize, dedup, score, store — under a frozen clock, one hour apart, so
the demo exercises the product rather than a hand-built fixture that could drift from it.

Usage:
    uv run python tools/seed_demo_db.py <output.db>
"""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jobtracker.collect.registry import load_registry
from jobtracker.core.clock import freeze
from jobtracker.core.db import apply_migrations, connect
from jobtracker.core.enums import Source
from jobtracker.core.geo import load_geo_index
from jobtracker.core.models import RawPosting
from jobtracker.match.profile import load_profile
from jobtracker.normalize.taxonomy import load_taxonomy
from jobtracker.runtime.pipeline import ingest
from jobtracker.store.companies import sync_companies
from jobtracker.store.schema import MIGRATIONS_DIR

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS = REPO_ROOT / "configs"
CORPUS = REPO_ROOT / "tests" / "fixtures" / "postings" / "corpus.jsonl"

# Every timestamp in the demo database derives from this instant.
DEMO_NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: seed_demo_db.py <output.db>", file=sys.stderr)
        return 1
    output = Path(sys.argv[1])
    output.unlink(missing_ok=True)

    conn = connect(output)
    apply_migrations(conn, MIGRATIONS_DIR)

    boards = load_registry(CONFIGS / "companies.yaml")
    sync_companies(conn, boards)
    conn.commit()
    taxonomy = load_taxonomy(CONFIGS / "taxonomy.yaml")
    geo = load_geo_index(CONFIGS / "geo.yaml")
    profile = load_profile(
        CONFIGS / "profile.yaml", company_tiers={b.company_slug: b.priority for b in boards}
    )

    entries = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line]
    for index, entry in enumerate(entries):
        fetched_at = DEMO_NOW - timedelta(hours=index)
        raw = RawPosting(
            source=Source(entry["source"]),
            company_slug=entry["company_slug"],
            source_job_id=entry["id"],
            url=f"https://example.invalid/jobs/{entry['id']}",
            title_raw=entry["title_raw"],
            description_raw=entry["description_raw"],
            location_raw=entry["location_raw"],
            department_raw=None,
            posted_at_raw=None,
            payload=json.dumps(entry, sort_keys=True).encode("utf-8"),
            fetched_at=fetched_at,
            content_hash=entry["id"],
        )
        hq_country = (
            entry["expect"]["locations"][0]["country"] if entry["expect"]["locations"] else None
        )
        with freeze(fetched_at):
            ingest(conn, raw, taxonomy=taxonomy, geo=geo, profile=profile, hq_country=hq_country)

    conn.commit()
    conn.close()
    print(f"wrote {output} ({len(entries)} corpus entries)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
