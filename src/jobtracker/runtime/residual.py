"""The LLM residual lane — blueprint/wp/WP12-match-llm.md §4.1.

`llama-server` is shared with OpenHands and is not always up, so nothing here
ever *waits* for it. An ambiguous posting is written to `llm_queue`; a drain,
run every `DRAIN_INTERVAL_MIN` minutes, tries the server and simply stops at
the first turn it cannot get — the posting stays queued with `attempts += 1`
and keeps its deterministic verdict in the meantime. There is deliberately no
remote fallback (ADR-010): a skipped turn costs thirty minutes, and no job
posting is urgent to the minute.

The urgent lane only moves the *moment* of the first attempt to ingest time,
with a short timeout. It does not jump any queue on the server side.
"""

import sqlite3
import time
from dataclasses import dataclass
from enum import StrEnum

import httpx

from jobtracker.core.clock import utc_now
from jobtracker.core.config import Settings
from jobtracker.core.logging import get_logger
from jobtracker.match.llm import LlmStatus, attempt_llm, rescore_with_llm
from jobtracker.match.prefilter import is_ambiguous, is_urgent
from jobtracker.match.profile import Profile
from jobtracker.store import llm_queue
from jobtracker.store.postings import get_posting, get_verdict, is_active, update_resolution
from jobtracker.store.search import get_description

_logger = get_logger(__name__)

DRAIN_INTERVAL_MIN = 30
_DRAIN_BATCH = 20

# After the server refuses one attempt, further *urgent* attempts within this
# window are skipped: a first-run burst of rank-1 postings must not stall the
# collection cycle for `urgent_timeout_s` each against a server that is down.
_URGENT_COOLDOWN_S = 60.0


@dataclass
class LlmClientConfig:
    """Where the LLM is and how long each lane may wait for it."""

    base_url: str
    model: str
    drain_timeout_s: int
    urgent_timeout_s: int = 5
    client: httpx.Client | None = None  # test seam, same as `classify_llm`'s
    _urgent_blocked_until: float = 0.0

    @classmethod
    def from_settings(cls, settings: Settings) -> "LlmClientConfig | None":
        """`None` when `JT_LLM_ENABLED=false` — the whole lane then simply doesn't exist."""
        if not settings.llm_enabled:
            return None
        return cls(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            drain_timeout_s=settings.llm_timeout_s,
        )


class EntryResult(StrEnum):
    RESOLVED = "resolved"  # fields applied, score recomputed, verdict stored
    QUARANTINED = "quarantined"  # non-conforming or under-confident: deterministic verdict stays
    REQUEUED = "requeued"  # server unavailable this turn
    DROPPED = "dropped"  # posting gone, deactivated, or no longer ambiguous


@dataclass(frozen=True)
class DrainResult:
    resolved: int = 0
    quarantined: int = 0
    dropped: int = 0
    requeued: int = 0
    server_available: bool = True
    remaining: int = 0


def process_entry(
    conn: sqlite3.Connection,
    posting_id: str,
    *,
    profile: Profile,
    cfg: LlmClientConfig,
    timeout_s: int,
) -> EntryResult:
    """One attempt for one queued posting. Commits its own outcome."""
    posting = get_posting(conn, posting_id)
    verdict = get_verdict(conn, posting_id)
    if posting is None or verdict is None or not is_active(conn, posting_id):
        llm_queue.remove(conn, posting_id)
        conn.commit()
        return EntryResult.DROPPED

    description = get_description(conn, posting_id) or ""
    if posting.resolver_stage == "llm" or not is_ambiguous(
        posting, verdict, profile=profile, description=description
    ):
        llm_queue.remove(conn, posting_id)
        conn.commit()
        return EntryResult.DROPPED

    outcome = attempt_llm(
        posting,
        description=description,
        timeout_s=timeout_s,
        base_url=cfg.base_url,
        model=cfg.model,
        max_description_chars=profile.llm.max_description_chars,
        client=cfg.client,
    )
    if outcome.status == LlmStatus.UNAVAILABLE:
        llm_queue.record_skipped_attempt(conn, posting_id, now=utc_now())
        conn.commit()
        return EntryResult.REQUEUED

    rescored = (
        rescore_with_llm(posting, outcome.verdict, profile=profile)
        if outcome.verdict is not None
        else None
    )
    if rescored is None:
        # Non-conforming or under-confident: never an alert, never a promotion.
        llm_queue.remove(conn, posting_id)
        conn.commit()
        return EntryResult.QUARANTINED

    updated, new_verdict = rescored
    update_resolution(conn, updated, new_verdict)
    llm_queue.remove(conn, posting_id)
    conn.commit()
    _logger.info(
        "llm_resolved",
        posting_id=posting_id,
        tier_before=verdict.tier.value,
        tier_after=new_verdict.tier.value,
        score_before=verdict.score,
        score_after=new_verdict.score,
    )
    return EntryResult.RESOLVED


def drain_queue(
    conn: sqlite3.Connection, *, profile: Profile, cfg: LlmClientConfig, limit: int = _DRAIN_BATCH
) -> DrainResult:
    """One deferred-lane turn. Stops at the first unavailable server — no hammering."""
    resolved = quarantined = dropped = requeued = 0
    available = True
    for entry in llm_queue.pending(conn, limit):
        result = process_entry(
            conn, entry.posting_id, profile=profile, cfg=cfg, timeout_s=cfg.drain_timeout_s
        )
        if result == EntryResult.RESOLVED:
            resolved += 1
        elif result == EntryResult.QUARANTINED:
            quarantined += 1
        elif result == EntryResult.DROPPED:
            dropped += 1
        else:
            requeued += 1
            available = False
            break
    remaining = llm_queue.depth(conn)
    _logger.info(
        "llm_drain_done",
        resolved=resolved,
        quarantined=quarantined,
        dropped=dropped,
        requeued=requeued,
        server_available=available,
        remaining=remaining,
    )
    return DrainResult(
        resolved=resolved,
        quarantined=quarantined,
        dropped=dropped,
        requeued=requeued,
        server_available=available,
        remaining=remaining,
    )


def queue_if_ambiguous(
    conn: sqlite3.Connection,
    posting_id: str,
    *,
    profile: Profile,
    cfg: LlmClientConfig,
    description: str,
) -> bool:
    """Called by `pipeline.ingest` for a new or changed posting; `True` if queued.

    Queues, then — only for an urgent posting and only when the server has not
    just refused us — makes one immediate short-timeout attempt. Whatever
    happens the posting already has its deterministic verdict stored, so a
    failure here costs nothing: it just waits for the next drain.
    """
    posting = get_posting(conn, posting_id)
    verdict = get_verdict(conn, posting_id)
    if posting is None or verdict is None or posting.resolver_stage == "llm":
        return False
    if not is_ambiguous(posting, verdict, profile=profile, description=description):
        return False

    urgent = is_urgent(posting, verdict, profile=profile)
    llm_queue.enqueue(conn, posting_id, urgent=urgent, now=utc_now())
    conn.commit()

    if urgent and time.monotonic() >= cfg._urgent_blocked_until:
        result = process_entry(
            conn, posting_id, profile=profile, cfg=cfg, timeout_s=cfg.urgent_timeout_s
        )
        if result == EntryResult.REQUEUED:
            cfg._urgent_blocked_until = time.monotonic() + _URGENT_COOLDOWN_S
    return True
