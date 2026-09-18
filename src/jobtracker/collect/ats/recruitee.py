"""Recruitee collector — blueprint/11-SOURCES.md §3.

`GET https://{token}.recruitee.com/api/offers/`, one call, no pagination —
the description is already in the list response.
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


class RecruiteeCollector:
    source = Source.RECRUITEE

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        url = f"https://{board.token}.recruitee.com/api/offers/"
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
        if not isinstance(data, dict) or not isinstance(data.get("offers"), list):
            raise SourceSchemaChanged(
                f"recruitee: unexpected payload shape for board {board.token!r}"
            )

        postings = []
        for offer in data["offers"]:
            raw = _map_offer(board, offer, fetched_at)
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


def _map_offer(board: Board, offer: Any, fetched_at: datetime) -> RawPosting | None:
    if not isinstance(offer, dict):
        _logger.info(
            "collect_posting_skipped",
            source="recruitee",
            company_slug=board.company_slug,
            reason="not_a_mapping",
        )
        return None

    offer_id = offer.get("id")
    title = offer.get("title")
    url = offer.get("careers_apply_url") or offer.get("careers_url")
    if offer_id is None or not title or not url:
        _logger.info(
            "collect_posting_skipped",
            source="recruitee",
            company_slug=board.company_slug,
            reason="missing_required_field",
        )
        return None

    location_raw = _location_text(offer)
    description_raw = offer.get("description") or ""
    title_str = str(title)

    return RawPosting(
        source=Source.RECRUITEE,
        company_slug=board.company_slug,
        source_job_id=str(offer_id),
        url=str(url),
        title_raw=title_str,
        description_raw=description_raw,
        location_raw=location_raw,
        department_raw=offer.get("department") or None,
        posted_at_raw=offer.get("published_at"),
        payload=json.dumps(offer).encode("utf-8"),
        fetched_at=fetched_at,
        content_hash=content_hash(title_str, description_raw, location_raw),
    )


def _location_text(offer: Any) -> str | None:
    locations = offer.get("locations")
    if isinstance(locations, list) and locations:
        names = [loc.get("name") or loc.get("city") for loc in locations if isinstance(loc, dict)]
        text = "; ".join(str(n) for n in names if n)
        if text:
            return text
    return offer.get("country") or None
