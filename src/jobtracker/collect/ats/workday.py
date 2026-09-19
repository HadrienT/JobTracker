"""Workday collector — blueprint/11-SOURCES.md §3, blueprint/wp/WP06-collect-ats2.md §2.

The list endpoint never carries a description, so a naive implementation
makes one detail request per posting — for a bank with 800 open roles, that
is 800 requests a cycle, guaranteed to blow the run's budget. Two guards cut
that down, in the order the WP06 blueprint prescribes:

1. A coarse, generous title pre-filter: only titles that could plausibly be
   engineering/quant roles get a detail request at all. A false positive
   just costs one extra request; a false negative still keeps the posting
   (with an empty description) rather than dropping it.
2. A summary-hash cache: a posting whose title/location have not changed
   since a previous cycle reuses its previously-fetched description instead
   of asking for it again. The cache is supplied by the caller (`known`) —
   this module has no store access (contract D5) and no memory between runs.

`tenant`/`wd`/`site` come from `Board.token` and `Board.extra`, filled in by
hand through real network-tab reconnaissance (never guessed — interdit n°12).
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from jobtracker.collect.http import BUDGET_EXHAUSTED, NOT_MODIFIED, HttpSession
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Source
from jobtracker.core.errors import BoardNotFound, ConfigError, SourceSchemaChanged
from jobtracker.core.hashing import content_hash
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board, CollectResult, RawPosting

_logger = get_logger(__name__)

_PAGE_SIZE = 20

# A cheap, deliberately generous request-budget filter — never a role
# classification (that is normalize's job). Skipping a detail fetch never
# drops a posting, it only leaves its description empty for this cycle.
_RELEVANT_TITLE_MARKERS = (
    "engineer",
    "developer",
    "quant",
    "scientist",
    "programmer",
    "software",
    "technology",
    "machine learning",
    "research",
)


@dataclass(frozen=True)
class KnownWorkdaySummary:
    """What the caller already knows about a posting from a previous cycle."""

    summary_hash: str
    description_raw: str


@dataclass(frozen=True)
class _FetchContext:
    detail_url_base: str
    public_url_base: str
    fetched_at: datetime
    known: Mapping[tuple[str, str], KnownWorkdaySummary]


@dataclass
class WorkdayCollector:
    source: Source = field(default=Source.WORKDAY, init=False)
    known: Mapping[tuple[str, str], KnownWorkdaySummary] = field(default_factory=dict)

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        started = time.monotonic()
        fetched_at = utc_now()
        tenant, wd, site = _workday_coordinates(board)
        host = f"https://{tenant}.wd{wd}.myworkdayjobs.com"
        list_url = f"{host}/wday/cxs/{tenant}/{site}/jobs"
        detail_url_base = f"{host}/wday/cxs/{tenant}/{site}"  # externalPath already starts "/job/"
        public_url_base = f"{host}/{site}"

        summaries, requests_made, truncated = _paginate(board, session, list_url)
        context = _FetchContext(detail_url_base, public_url_base, fetched_at, self.known)

        postings: list[RawPosting] = []
        for summary in summaries:
            raw, detail_requests, was_truncated = _map_summary(board, summary, session, context)
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


def _workday_coordinates(board: Board) -> tuple[str, str, str]:
    wd = board.extra.get("wd")
    site = board.extra.get("site")
    if not board.token or not wd or not site:
        raise ConfigError(
            f"workday board {board.company_slug!r} is missing token/extra.wd/extra.site "
            "— reconnaissance (blueprint/wp/WP06-collect-ats2.md §2) was not recorded"
        )
    return board.token, wd, site


def _paginate(board: Board, session: HttpSession, list_url: str) -> tuple[list[Any], int, bool]:
    summaries: list[Any] = []
    offset = 0
    total: int | None = None
    requests_made = 0
    truncated = False

    while True:
        body = {"appliedFacets": {}, "limit": _PAGE_SIZE, "offset": offset, "searchText": ""}
        data = session.post_json(list_url, json=body)
        if data is BUDGET_EXHAUSTED:
            truncated = True
            break
        if data is NOT_MODIFIED:
            break
        if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
            raise SourceSchemaChanged(
                f"workday: unexpected list payload for board {board.company_slug!r}"
            )
        requests_made += 1
        page = data["jobPostings"]
        page_total = data.get("total")
        # Workday reports `total` on the first page only and answers 0 on the next ones: the
        # first figure is the real one, and a later 0 must not read as "that was the last page".
        if total is None and isinstance(page_total, int):
            total = page_total
        if not page:
            if total is not None and offset < total:
                _logger.info(
                    "workday_pagination_total_mismatch",
                    company_slug=board.company_slug,
                    declared_total=total,
                    served=offset,
                )
            break
        summaries.extend(page)
        offset += len(page)
        if total is not None and offset >= total:
            break

    return summaries, requests_made, truncated


def _map_summary(
    board: Board, summary: Any, session: HttpSession, context: _FetchContext
) -> tuple[RawPosting | None, int, bool]:
    if not isinstance(summary, dict):
        _logger.info(
            "collect_posting_skipped",
            source="workday",
            company_slug=board.company_slug,
            reason="not_a_mapping",
        )
        return None, 0, False

    title = summary.get("title")
    external_path = summary.get("externalPath")
    if not title or not external_path:
        _logger.info(
            "collect_posting_skipped",
            source="workday",
            company_slug=board.company_slug,
            reason="missing_required_field",
        )
        return None, 0, False

    location_raw = summary.get("locationsText")
    summary_hash = content_hash(title, "", location_raw)
    cached = context.known.get((board.company_slug, external_path))
    posted_at_raw = summary.get("postedOn")
    requests_made = 0
    truncated = False

    if cached is not None and cached.summary_hash == summary_hash:
        description_raw = cached.description_raw
    elif not _looks_relevant(title):
        _logger.info(
            "collect_detail_skipped",
            source="workday",
            company_slug=board.company_slug,
            reason="title_prefilter",
        )
        description_raw = ""
    else:
        description_raw, detail_posted_at, requests_made, truncated = _fetch_detail(
            board, session, context.detail_url_base, external_path
        )
        posted_at_raw = detail_posted_at or posted_at_raw

    return (
        RawPosting(
            source=Source.WORKDAY,
            company_slug=board.company_slug,
            source_job_id=external_path,
            url=f"{context.public_url_base}{external_path}",
            title_raw=str(title),
            description_raw=description_raw,
            location_raw=location_raw,
            department_raw=None,
            posted_at_raw=posted_at_raw,
            payload=_encode(summary),
            fetched_at=context.fetched_at,
            content_hash=content_hash(str(title), description_raw, location_raw),
        ),
        requests_made,
        truncated,
    )


def _fetch_detail(
    board: Board, session: HttpSession, detail_url_base: str, external_path: str
) -> tuple[str, str | None, int, bool]:
    url = f"{detail_url_base}{external_path}"
    try:
        data = session.get_json(url)
    except BoardNotFound:
        # A 404 here means this one posting's detail page is gone (closed
        # between the list and detail calls), not that the board is wrong —
        # blueprint/wp/WP06-collect-ats2.md §5: keep the posting, drop only
        # the description.
        _logger.info(
            "collect_detail_not_found", source="workday", company_slug=board.company_slug, url=url
        )
        return "", None, 1, False

    if data is BUDGET_EXHAUSTED:
        return "", None, 0, True
    if data is NOT_MODIFIED:
        return "", None, 1, False
    if not isinstance(data, dict) or not isinstance(data.get("jobPostingInfo"), dict):
        raise SourceSchemaChanged(f"workday: unexpected detail payload at {url}")

    info = data["jobPostingInfo"]
    description = info.get("jobDescription") or ""
    posted_at = info.get("startDate")
    return description, posted_at, 1, False


def _looks_relevant(title: str) -> bool:
    title_l = title.lower()
    return any(marker in title_l for marker in _RELEVANT_TITLE_MARKERS)


def _encode(summary: Mapping[str, Any]) -> bytes:
    return json.dumps(summary).encode("utf-8")
