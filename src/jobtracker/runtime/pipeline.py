"""Ingest one `RawPosting` — blueprint/05-SEQUENCES.md §1, blueprint/wp/WP08-runtime.md §2.

Two orderings are non-negotiable, and this module is the one place that
enforces them:

1. **The raw payload is archived before `normalize()` runs.** If the
   normalizer crashes on an exotic posting, the payload is already durable
   and a later replay can retry it — the reverse order loses exactly the
   cases worth replaying.
2. **Dedup resolution precedes `match.evaluate()`.** Scoring an alias burns
   CPU (and GPU, once the LLM prefilter exists) on a row that is never
   displayed.
"""

import sqlite3
from dataclasses import dataclass
from typing import Literal

from jobtracker.core.enums import Tier
from jobtracker.core.geo import GeoIndex
from jobtracker.core.logging import get_logger
from jobtracker.core.models import RawPosting
from jobtracker.match.profile import Profile
from jobtracker.match.score import evaluate
from jobtracker.normalize.cascade import normalize
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.normalize.text import html_to_text
from jobtracker.runtime.residual import LlmClientConfig, queue_if_ambiguous
from jobtracker.store.archive import archive_payload
from jobtracker.store.companies import ensure_discovered_company, get_company
from jobtracker.store.postings import (
    previous_content_hash,
    record_alias,
    record_raw_inputs,
    resolve_dedup,
    resolve_posting_id,
    upsert_posting,
)
from jobtracker.store.search import index_description

_logger = get_logger(__name__)

IngestOutcome = Literal["new", "updated", "aliased", "normalize_error"]


@dataclass(frozen=True)
class IngestResult:
    outcome: IngestOutcome
    posting_id: str | None
    tier: Tier | None = None


def ingest(
    conn: sqlite3.Connection,
    raw: RawPosting,
    *,
    taxonomy: Taxonomy,
    geo: GeoIndex,
    profile: Profile,
    hq_country: str | None = None,
    llm: LlmClientConfig | None = None,
) -> IngestResult:
    posting_id = resolve_posting_id(conn, raw.source, raw.company_slug, raw.source_job_id)
    previous_hash = previous_content_hash(conn, raw.source, raw.company_slug, raw.source_job_id)
    archive_payload(conn, posting_id, raw.payload, raw.fetched_at)
    conn.commit()

    # The archive above keeps the payload as the source sent it; everything downstream —
    # the normalizer's regexes, the search text, the UI, the LLM prompt — reads readable text.
    description = html_to_text(raw.description_raw)

    try:
        posting = normalize(
            raw.model_copy(update={"description_raw": description}),
            taxonomy=taxonomy,
            geo=geo,
            hq_country=hq_country,
        )
    except Exception:
        _logger.error(
            "pipeline_normalize_failed",
            source=raw.source.value,
            company_slug=raw.company_slug,
            source_job_id=raw.source_job_id,
            posting_id=posting_id,
            exc_info=True,
        )
        return IngestResult(outcome="normalize_error", posting_id=posting_id)

    posting = posting.model_copy(update={"posting_id": posting_id})

    # `postings.company_slug` is a foreign key: an employer only an aggregator
    # knows (blueprint/wp/WP13-aggregators.md §4) needs a row before its postings.
    if get_company(conn, raw.company_slug) is None:
        ensure_discovered_company(
            conn,
            slug=raw.company_slug,
            name=raw.company_name or raw.company_slug,
            source=raw.source,
            hq_country=hq_country or "",
        )

    alias_of = resolve_dedup(conn, posting)
    if alias_of is not None:
        record_alias(conn, alias_of, raw)
        conn.commit()
        return IngestResult(outcome="aliased", posting_id=alias_of)

    verdict = evaluate(posting, profile=profile)
    final_id = upsert_posting(conn, posting, verdict)
    index_description(conn, final_id, description)
    record_raw_inputs(
        conn, final_id, location_raw=raw.location_raw, posted_at_raw=raw.posted_at_raw
    )
    conn.commit()

    # An unchanged re-fetch keeps whatever verdict is stored — including one the
    # LLM already produced — so only a new or changed posting can need the LLM.
    if llm is not None and previous_hash != raw.content_hash:
        queue_if_ambiguous(conn, final_id, profile=profile, cfg=llm, description=description)

    outcome: IngestOutcome = "new" if previous_hash is None else "updated"
    return IngestResult(outcome=outcome, posting_id=final_id, tier=verdict.tier)
