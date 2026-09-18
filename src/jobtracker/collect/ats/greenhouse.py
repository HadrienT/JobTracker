"""Greenhouse collector — blueprint/11-SOURCES.md §2.

`GET /v1/boards/{token}/jobs?content=true`, one call, no pagination.
`content=true` gives the HTML-escaped description; `location.name` is free
text, left as-is for `normalize.parse_location` to interpret.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
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


class GreenhouseCollector:
    source = Source.GREENHOUSE

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board.token}/jobs?content=true"
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
                f"greenhouse: unexpected payload shape for board {board.token!r}"
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
            source="greenhouse",
            company_slug=board.company_slug,
            reason="not_a_mapping",
        )
        return None
    job_id = job.get("id")
    title = job.get("title")
    absolute_url = job.get("absolute_url")
    if job_id is None or not title or not absolute_url:
        _logger.info(
            "collect_posting_skipped",
            source="greenhouse",
            company_slug=board.company_slug,
            reason="missing_required_field",
        )
        return None

    location = job.get("location")
    location_raw = location.get("name") if isinstance(location, dict) else None
    description_raw = job.get("content") or ""
    title_str = str(title)

    return RawPosting(
        source=Source.GREENHOUSE,
        company_slug=board.company_slug,
        source_job_id=str(job_id),
        url=str(absolute_url),
        title_raw=title_str,
        description_raw=description_raw,
        location_raw=location_raw,
        department_raw=_first_department(job),
        posted_at_raw=job.get("updated_at"),
        payload=json.dumps(job).encode("utf-8"),
        fetched_at=fetched_at,
        content_hash=content_hash(title_str, description_raw, location_raw),
    )


def _first_department(job: Mapping[str, Any]) -> str | None:
    departments = job.get("departments")
    if isinstance(departments, list) and departments:
        first = departments[0]
        if isinstance(first, dict):
            name = first.get("name")
            return str(name) if name else None
    return None
