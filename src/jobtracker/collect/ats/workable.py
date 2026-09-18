"""Workable collector — blueprint/11-SOURCES.md §3.

`GET /api/v1/widget/accounts/{token}?details=true`, one call, no pagination
— the description is already in the list response.
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


class WorkableCollector:
    source = Source.WORKABLE

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        url = f"https://apply.workable.com/api/v1/widget/accounts/{board.token}?details=true"
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
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise SourceSchemaChanged(
                f"workable: unexpected payload shape for board {board.token!r}"
            )

        postings = []
        for job in data["jobs"]:
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
            source="workable",
            company_slug=board.company_slug,
            reason="not_a_mapping",
        )
        return None

    title = job.get("title")
    shortcode = job.get("shortcode")
    url = job.get("url") or job.get("shortlink")
    if not title or not shortcode or not url:
        _logger.info(
            "collect_posting_skipped",
            source="workable",
            company_slug=board.company_slug,
            reason="missing_required_field",
        )
        return None

    location_raw = _location_text(job)
    description_raw = job.get("description") or ""
    title_str = str(title)

    return RawPosting(
        source=Source.WORKABLE,
        company_slug=board.company_slug,
        source_job_id=str(shortcode),
        url=str(url),
        title_raw=title_str,
        description_raw=description_raw,
        location_raw=location_raw,
        department_raw=job.get("department") or None,
        posted_at_raw=job.get("published_on") or job.get("created_at"),
        payload=json.dumps(job).encode("utf-8"),
        fetched_at=fetched_at,
        content_hash=content_hash(title_str, description_raw, location_raw),
    )


def _location_text(job: Any) -> str | None:
    parts = [job.get("city"), job.get("state"), job.get("country")]
    text = ", ".join(str(p) for p in parts if p)
    return text or None
