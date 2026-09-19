"""Drive the whole-feed LLM re-read — blueprint/wp/WP19-llm-review.md.

`match.review` decides; this module reads from the database, asks the server, hands the reply to
`plan_review`, and writes the plan back. Two properties matter more than any feature:

- **A dry run writes nothing.** The first run on real data is `--dry-run`, and what it prints is
  what a real run would do, because both go through the same `plan_review`.
- **A stopped server is not an error.** The run ends at the first refused turn, with everything
  before it committed, and the next run picks up exactly where it stopped (a posting is "read"
  once its review row exists, for its content and its prompt version).
"""

import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError

from jobtracker.core.clock import utc_now
from jobtracker.core.enums import RemoteMode, ReviewOutcome, SalaryPeriod, Seniority, VisaStatus
from jobtracker.core.geo import GeoIndex, resolve_city
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Compensation, Location, Posting
from jobtracker.match.llm import LlmStatus, chat_json
from jobtracker.match.profile import Profile
from jobtracker.match.review import (
    REVIEW_SYSTEM_PROMPT,
    ReviewOutput,
    ReviewPlan,
    ReviewSources,
    plan_review,
    review_user_content,
)
from jobtracker.match.score import evaluate
from jobtracker.runtime.residual import LlmClientConfig
from jobtracker.store import llm_reviews
from jobtracker.store.postings import get_posting, is_active, update_resolution
from jobtracker.store.search import get_description

_logger = get_logger(__name__)

REVERTIBLE_FIELDS = (
    "compensation",
    "locations",
    "seniority",
    "min_years",
    "visa_sponsorship",
    "phd_required",
    "closes_at",
)


def _restored(posting: Posting, field: str, before: Any, geo: GeoIndex) -> dict[str, Any]:
    """The `Posting` updates that put `field` back to the value it had before the LLM changed it."""
    if field == "compensation":
        current = posting.compensation
        return {
            "compensation": Compensation(
                amount_min=None if before["amount_min"] is None else Decimal(before["amount_min"]),
                amount_max=None if before["amount_max"] is None else Decimal(before["amount_max"]),
                currency=before["currency"],
                period=None if before["period"] is None else SalaryPeriod(before["period"]),
                bonus_mentioned=current.bonus_mentioned,
                equity_mentioned=current.equity_mentioned,
                raw=current.raw,
            )
        }
    if field == "locations":
        raw = posting.locations[0].raw if posting.locations else None
        restored = []
        for entry in before:
            city = entry["city"]
            resolved = (
                None if city is None else resolve_city(geo, city, hq_country=entry["country"])
            )
            restored.append(
                Location(
                    city=city,
                    country=entry["country"],
                    region=None if resolved is None else resolved.region,
                    remote_mode=RemoteMode(entry["remote_mode"]),
                    raw=raw,
                )
            )
        return {"locations": tuple(restored)}
    if field == "seniority":
        return {"seniority": Seniority(before)}
    if field == "visa_sponsorship":
        return {"visa_sponsorship": VisaStatus(before), "visa_evidence": None}
    if field == "closes_at":
        return {"closes_at": None if before is None else datetime.fromisoformat(before)}
    return {field: before}  # min_years, phd_required: plain values


def revert_corrections(
    conn: sqlite3.Connection,
    *,
    field: str,
    profile: Profile,
    geo: GeoIndex,
    posting_ids: list[str] | None = None,
) -> int:
    """Undo the LLM's corrections of one field: restore the value before, rescore, and queue the
    posting for a fresh reading. Returns how many postings were reverted."""
    if field not in REVERTIBLE_FIELDS:
        raise ValueError(f"cannot revert {field!r}; one of {', '.join(REVERTIBLE_FIELDS)}")
    reverted = 0
    for posting_id, corrections in llm_reviews.current_corrections_of_field(
        conn, field, posting_ids=posting_ids
    ):
        posting = get_posting(conn, posting_id)
        if posting is None or not corrections:
            continue
        # The oldest correction's "before" is what the rules had; later ones stacked on it.
        updated = posting.model_copy(update=_restored(posting, field, corrections[0].before, geo))
        update_resolution(conn, updated, evaluate(updated, profile=profile))
        llm_reviews.forget_field(conn, posting_id, field)
        reverted += 1
    conn.commit()
    _logger.info("llm_corrections_reverted", field=field, postings=reverted)
    return reverted


@dataclass(frozen=True)
class ReviewStep:
    """One posting's turn: its plan, or `None` when the server did not answer."""

    posting_id: str
    title: str
    plan: ReviewPlan | None  # None = the server was unavailable: nothing was read
    output: ReviewOutput | None = None  # what the model actually said, for the report


@dataclass
class ReviewStats:
    read: int = 0
    corrected: int = 0
    confirmed: int = 0
    set_aside: int = 0
    skipped: int = 0
    server_available: bool = True
    corrections_by_field: Counter[str] = field(default_factory=Counter)
    refused: Counter[str] = field(default_factory=Counter)
    unknown_cities: Counter[tuple[str, str | None]] = field(default_factory=Counter)

    def add(self, plan: ReviewPlan) -> None:
        self.read += 1
        if plan.outcome is ReviewOutcome.CORRECTED:
            self.corrected += 1
        elif plan.outcome is ReviewOutcome.CONFIRMED:
            self.confirmed += 1
        else:
            self.set_aside += 1
        for correction in plan.corrections:
            self.corrections_by_field[correction.field] += 1
        for reason in plan.refused:
            self.refused[reason] += 1
        for city in plan.unknown_cities:
            self.unknown_cities[city] += 1


def _location_raw(conn: sqlite3.Connection, posting_id: str) -> str | None:
    row = conn.execute(
        "SELECT location_raw FROM postings WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    return None if row is None else row["location_raw"]


def review_posting(
    conn: sqlite3.Connection,
    posting_id: str,
    *,
    profile: Profile,
    geo: GeoIndex,
    cfg: LlmClientConfig,
    dry_run: bool,
) -> ReviewStep | None:
    """Read one posting. `None` = nothing to read (gone, inactive, no text)."""
    posting = get_posting(conn, posting_id)
    if posting is None or not is_active(conn, posting_id):
        return None
    description = get_description(conn, posting_id) or ""
    sources = ReviewSources(
        title=posting.title_raw, location=_location_raw(conn, posting_id), description=description
    )
    reply = chat_json(
        system=REVIEW_SYSTEM_PROMPT,
        user=review_user_content(
            posting, sources, max_description_chars=profile.review.max_description_chars
        ),
        schema_name="posting_review",
        schema=ReviewOutput.model_json_schema(),
        timeout_s=cfg.drain_timeout_s,
        base_url=cfg.base_url,
        model=cfg.model,
        log_id=posting_id,
        max_tokens=profile.review.max_output_tokens,
        client=cfg.client,
    )
    if reply.status is LlmStatus.UNAVAILABLE:
        return ReviewStep(posting_id, posting.title_raw, None)

    output: ReviewOutput | None = None
    if reply.data is not None:
        try:
            output = ReviewOutput.model_validate(reply.data)
        except ValidationError as exc:
            _logger.warning("review_response_non_conforming", posting_id=posting_id, error=str(exc))
    plan = plan_review(posting, output, sources=sources, profile=profile, geo=geo)

    if not dry_run:
        now = utc_now()
        if plan.corrections:
            update_resolution(conn, plan.posting, evaluate(plan.posting, profile=profile))
            llm_reviews.record_corrections(
                conn,
                posting_id,
                list(plan.corrections),
                content_hash=posting.content_hash,
                review_version=profile.review.version,
                now=now,
            )
        llm_reviews.record_review(
            conn,
            posting_id,
            content_hash=posting.content_hash,
            review_version=profile.review.version,
            model=cfg.model,
            outcome=plan.outcome,
            confidence=plan.confidence,
            now=now,
        )
        conn.commit()
        if plan.corrections:
            _logger.info(
                "llm_review_corrected",
                posting_id=posting_id,
                fields=[c.field for c in plan.corrections],
            )
    return ReviewStep(posting_id, posting.title_raw, plan, output)


def review_all(
    conn: sqlite3.Connection,
    *,
    profile: Profile,
    geo: GeoIndex,
    cfg: LlmClientConfig,
    limit: int | None = None,
    dry_run: bool = False,
    posting_ids: list[str] | None = None,
    on_step: Callable[[ReviewStep, ReviewStats], None] | None = None,
) -> ReviewStats:
    """Read every unreviewed posting, best score first, until done or the server stops."""
    ids = (
        posting_ids
        if posting_ids is not None
        else llm_reviews.unreviewed_posting_ids(
            conn, review_version=profile.review.version, limit=limit
        )
    )
    stats = ReviewStats()
    for posting_id in ids:
        step = review_posting(conn, posting_id, profile=profile, geo=geo, cfg=cfg, dry_run=dry_run)
        if step is None:
            stats.skipped += 1
            continue
        if step.plan is None:
            stats.server_available = False
            break
        stats.add(step.plan)
        if on_step is not None:
            on_step(step, stats)
    return stats
