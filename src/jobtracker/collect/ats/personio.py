"""Personio collector — blueprint/11-SOURCES.md §3.

`GET https://{token}.jobs.personio.de/xml`, one call, no pagination — but
XML, not JSON, the one family in this project that is. A board technically
found here can still be a template nobody ever filled in (three Lorem-ipsum
postings is a real, observed case — see the `kaiko` fixture) — that is not
this collector's problem to solve, it is normalize's and P3's, so a
Lorem-ipsum position is collected like any other.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import datetime

from jobtracker.collect.http import HttpSession
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceSchemaChanged
from jobtracker.core.hashing import content_hash
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board, CollectResult, RawPosting

_logger = get_logger(__name__)


class PersonioCollector:
    source = Source.PERSONIO

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        url = f"https://{board.token}.jobs.personio.de/xml"
        started = time.monotonic()
        fetched_at = utc_now()
        text = session.get_text(url)

        # An empty body covers both "no positions" and a spent request
        # budget (collect/http.py's get_text cannot tell the two apart —
        # neither is exercised by a single-call collector like this one in
        # practice) — treated the same, safely, as an empty run.
        if not text.strip():
            return CollectResult(
                board=board,
                postings=(),
                requests_made=1,
                duration_ms=_elapsed_ms(started),
                truncated=False,
            )

        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise SourceSchemaChanged(f"personio: malformed XML for board {board.token!r}") from exc

        postings = []
        for position in root.findall("position"):
            raw = _map_position(board, position, fetched_at)
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


def _map_position(board: Board, position: ET.Element, fetched_at: datetime) -> RawPosting | None:
    job_id = position.findtext("id")
    title = position.findtext("name")
    if not job_id or not title:
        _logger.info(
            "collect_posting_skipped",
            source="personio",
            company_slug=board.company_slug,
            reason="missing_required_field",
        )
        return None

    location_raw = position.findtext("office") or None
    department_raw = position.findtext("department") or None
    posted_at_raw = position.findtext("createdAt")
    description_raw = _join_descriptions(position)
    url = f"https://{board.token}.jobs.personio.de/job/{job_id}"

    return RawPosting(
        source=Source.PERSONIO,
        company_slug=board.company_slug,
        source_job_id=str(job_id),
        url=url,
        title_raw=title,
        description_raw=description_raw,
        location_raw=location_raw,
        department_raw=department_raw,
        posted_at_raw=posted_at_raw,
        payload=ET.tostring(position, encoding="utf-8"),
        fetched_at=fetched_at,
        content_hash=content_hash(title, description_raw, location_raw),
    )


def _join_descriptions(position: ET.Element) -> str:
    parts = []
    for job_description in position.findall("jobDescriptions/jobDescription"):
        name = job_description.findtext("name") or ""
        value = job_description.findtext("value") or ""
        if value.strip():
            parts.append(f"{name}\n{value}" if name else value)
    return "\n\n".join(parts)
