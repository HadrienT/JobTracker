"""Ashby collector — blueprint/11-SOURCES.md §2.

`GET /posting-api/job-board/{token}?includeCompensation=true`, one call, no
pagination. `isListed=false` is a hidden posting — Ashby serves it anyway,
so this collector is the one place that must drop it (blueprint/wp/WP04-
collect-core.md §3). `includeCompensation` gives real ranges when a company
publishes them; kept in the archived `payload` for a future normalize stage,
since `RawPosting`'s text fields are the only channel normalize reads today.
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


class AshbyCollector:
    source = Source.ASHBY

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        url = (
            f"https://api.ashbyhq.com/posting-api/job-board/{board.token}?includeCompensation=true"
        )
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
            raise SourceSchemaChanged(f"ashby: unexpected payload shape for board {board.token!r}")

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
            source="ashby",
            company_slug=board.company_slug,
            reason="not_a_mapping",
        )
        return None
    if job.get("isListed") is False:
        _logger.info(
            "collect_posting_skipped",
            source="ashby",
            company_slug=board.company_slug,
            reason="not_listed",
        )
        return None

    job_id = job.get("id")
    title = job.get("title")
    url = job.get("jobUrl") or job.get("applyUrl")
    if not job_id or not title or not url:
        _logger.info(
            "collect_posting_skipped",
            source="ashby",
            company_slug=board.company_slug,
            reason="missing_required_field",
        )
        return None

    location = job.get("location")
    location_raw = str(location) if location else None
    department = job.get("department") or job.get("team")
    department_raw = str(department) if department else None
    description_raw = job.get("descriptionPlain") or job.get("descriptionHtml") or ""
    title_str = str(title)

    return RawPosting(
        source=Source.ASHBY,
        company_slug=board.company_slug,
        source_job_id=str(job_id),
        url=str(url),
        title_raw=title_str,
        description_raw=description_raw,
        location_raw=location_raw,
        department_raw=department_raw,
        posted_at_raw=job.get("publishedAt"),
        payload=json.dumps(job).encode("utf-8"),
        fetched_at=fetched_at,
        content_hash=content_hash(title_str, description_raw, location_raw),
    )
