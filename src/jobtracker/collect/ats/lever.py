"""Lever collector — blueprint/11-SOURCES.md §2.

`GET /v0/postings/{token}?mode=json`, one call, no pagination. The response
is a bare JSON list, not wrapped in an envelope. `categories.commitment`
("Full-Time"/"Intern") and the rest of `categories`/`lists` are precious
signal for WP03, but normalize only ever reads `RawPosting`'s flat text
fields — so nothing here is thrown away, it survives in the archived
`payload`, ready for a future normalize stage to read structurally.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from jobtracker.collect.http import BUDGET_EXHAUSTED, NOT_MODIFIED, HttpSession
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceSchemaChanged
from jobtracker.core.hashing import content_hash
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board, CollectResult, RawPosting

_logger = get_logger(__name__)


class LeverCollector:
    source = Source.LEVER

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        url = f"https://api.lever.co/v0/postings/{board.token}?mode=json"
        started = time.monotonic()
        fetched_at = utc_now()
        data = session.get_json(url)

        if data is BUDGET_EXHAUSTED:
            return CollectResult(
                board=board,
                postings=(),
                requests_made=0,
                duration_ms=_elapsed_ms(started),
                truncated=True,
            )
        if data is NOT_MODIFIED:
            return CollectResult(
                board=board,
                postings=(),
                requests_made=1,
                duration_ms=_elapsed_ms(started),
                truncated=False,
            )
        if not isinstance(data, list):
            raise SourceSchemaChanged(f"lever: unexpected payload shape for board {board.token!r}")

        postings = []
        for job in data:
            raw = _map_job(board, job, fetched_at)
            if raw is not None:
                postings.append(raw)
        return CollectResult(
            board=board,
            postings=tuple(postings),
            requests_made=1,
            duration_ms=_elapsed_ms(started),
            truncated=False,
        )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _map_job(board: Board, job: Any, fetched_at: datetime) -> RawPosting | None:
    if not isinstance(job, dict):
        _logger.info(
            "collect_posting_skipped",
            source="lever",
            company_slug=board.company_slug,
            reason="not_a_mapping",
        )
        return None
    job_id = job.get("id")
    title = job.get("text")
    url = job.get("hostedUrl") or job.get("applyUrl")
    if not job_id or not title or not url:
        _logger.info(
            "collect_posting_skipped",
            source="lever",
            company_slug=board.company_slug,
            reason="missing_required_field",
        )
        return None

    categories = job.get("categories")
    categories = categories if isinstance(categories, dict) else {}
    raw_location = categories.get("location")
    raw_department = categories.get("team") or categories.get("department")
    location_raw = str(raw_location) if raw_location else None
    department_raw = str(raw_department) if raw_department else None
    description_raw = (
        job.get("descriptionPlain")
        or job.get("description")
        or job.get("openingPlain")
        or job.get("opening")
        or ""
    )
    created_at = job.get("createdAt")
    title_str = str(title)

    return RawPosting(
        source=Source.LEVER,
        company_slug=board.company_slug,
        source_job_id=str(job_id),
        url=str(url),
        title_raw=title_str,
        description_raw=description_raw,
        location_raw=location_raw,
        department_raw=department_raw,
        posted_at_raw=str(created_at) if created_at is not None else None,
        payload=json.dumps(job).encode("utf-8"),
        fetched_at=fetched_at,
        content_hash=content_hash(title_str, description_raw, location_raw),
    )
