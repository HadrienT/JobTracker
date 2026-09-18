"""SmartRecruiters collector — blueprint/11-SOURCES.md §3.

`GET /v1/companies/{token}/postings?limit=100&offset={n}` paginates a
summary list with no description; each posting needs a second call to
`.../postings/{id}` for `jobAd.sections`. Unlike Workday, the boards this
collector serves are small (a handful of crypto/prop shops), so there is no
budget crisis here and no title pre-filter or cache — every posting just
gets its detail fetched.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from jobtracker.collect.http import BUDGET_EXHAUSTED, NOT_MODIFIED, HttpSession
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Source
from jobtracker.core.errors import BoardNotFound, SourceSchemaChanged
from jobtracker.core.hashing import content_hash
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board, CollectResult, RawPosting

_logger = get_logger(__name__)

_PAGE_SIZE = 100


class SmartRecruitersCollector:
    source = Source.SMARTRECRUITERS

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        started = time.monotonic()
        fetched_at = utc_now()
        base = f"https://api.smartrecruiters.com/v1/companies/{board.token}"

        summaries, requests_made, truncated = _paginate(board, session, base)

        postings: list[RawPosting] = []
        for summary in summaries:
            raw, detail_requests, was_truncated = _map_summary(
                board, summary, session, base, fetched_at
            )
            requests_made += detail_requests
            truncated = truncated or was_truncated
            if raw is not None:
                postings.append(raw)

        duration_ms = int((time.monotonic() - started) * 1000)
        return CollectResult(
            board=board,
            postings=tuple(postings),
            requests_made=requests_made,
            duration_ms=duration_ms,
            truncated=truncated,
        )


def _paginate(board: Board, session: HttpSession, base: str) -> tuple[list[Any], int, bool]:
    summaries: list[Any] = []
    offset = 0
    total: int | None = None
    requests_made = 0
    truncated = False

    while True:
        url = f"{base}/postings"
        data = session.get_json(url, params={"limit": str(_PAGE_SIZE), "offset": str(offset)})
        if data is BUDGET_EXHAUSTED:
            truncated = True
            break
        if data is NOT_MODIFIED:
            break
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            raise SourceSchemaChanged(
                f"smartrecruiters: unexpected list payload for board {board.company_slug!r}"
            )
        requests_made += 1
        page = data["content"]
        if not page:
            break
        summaries.extend(page)
        offset += len(page)
        found = data.get("totalFound")
        if isinstance(found, int):
            total = found
        if total is not None and offset >= total:
            break

    return summaries, requests_made, truncated


def _map_summary(
    board: Board, summary: Any, session: HttpSession, base: str, fetched_at: datetime
) -> tuple[RawPosting | None, int, bool]:
    if not isinstance(summary, dict):
        _logger.info(
            "collect_posting_skipped",
            source="smartrecruiters",
            company_slug=board.company_slug,
            reason="not_a_mapping",
        )
        return None, 0, False

    job_id = summary.get("id")
    title = summary.get("name")
    if not job_id or not title:
        _logger.info(
            "collect_posting_skipped",
            source="smartrecruiters",
            company_slug=board.company_slug,
            reason="missing_required_field",
        )
        return None, 0, False

    location = summary.get("location")
    location_raw = location.get("fullLocation") if isinstance(location, dict) else None
    department = summary.get("department")
    department_raw = department.get("label") if isinstance(department, dict) else None

    description_raw, url, requests_made, truncated = _fetch_detail(board, session, base, job_id)
    if not url:
        url = summary.get("ref") or f"{base}/postings/{job_id}"

    return (
        RawPosting(
            source=Source.SMARTRECRUITERS,
            company_slug=board.company_slug,
            source_job_id=str(job_id),
            url=str(url),
            title_raw=str(title),
            description_raw=description_raw,
            location_raw=location_raw,
            department_raw=department_raw,
            posted_at_raw=summary.get("releasedDate"),
            payload=json.dumps(summary).encode("utf-8"),
            fetched_at=fetched_at,
            content_hash=content_hash(str(title), description_raw, location_raw),
        ),
        requests_made,
        truncated,
    )


def _fetch_detail(
    board: Board, session: HttpSession, base: str, job_id: Any
) -> tuple[str, str | None, int, bool]:
    url = f"{base}/postings/{job_id}"
    try:
        data = session.get_json(url)
    except BoardNotFound:
        _logger.info(
            "collect_detail_not_found",
            source="smartrecruiters",
            company_slug=board.company_slug,
            url=url,
        )
        return "", None, 1, False

    if data is BUDGET_EXHAUSTED:
        return "", None, 0, True
    if data is NOT_MODIFIED:
        return "", None, 1, False
    if not isinstance(data, dict) or not isinstance(data.get("jobAd"), dict):
        raise SourceSchemaChanged(f"smartrecruiters: unexpected detail payload at {url}")

    description_raw = _join_sections(data["jobAd"].get("sections"))
    posting_url = data.get("postingUrl") or data.get("applyUrl")
    return description_raw, posting_url, 1, False


def _join_sections(sections: Any) -> str:
    if not isinstance(sections, dict):
        return ""
    parts = []
    for section in sections.values():
        if isinstance(section, dict) and section.get("text"):
            parts.append(str(section["text"]))
    return "\n\n".join(parts)
