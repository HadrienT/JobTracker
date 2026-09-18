"""Adzuna — blueprint/wp/WP13-aggregators.md §3.1. The one clean aggregator.

Official API, free with a key (`JT_ADZUNA_APP_ID` / `JT_ADZUNA_APP_KEY`): no terms
to circumvent, no anti-bot, a stable contract. Written from Adzuna's public API
documentation (`GET /v1/api/jobs/{country}/search/{page}`); it has **not** been run
against the live API, since that needs a key — and Adzuna's actual coverage of
quant finance is still `[À CONFIRMER]`: judge it on the first real run's discovery
report before deciding the other aggregators are worth keeping.

Adzuna returns a truncated description snippet, not the full text; the posting is
still useful for discovery and as an alias, but an ATS posting always wins as canonical.
"""

import json
import time
from datetime import datetime
from typing import Any

from jobtracker.collect.aggregators.common import get_json_checked, slugify_employer
from jobtracker.collect.http import HttpSession
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceSchemaChanged
from jobtracker.core.hashing import content_hash
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board, CollectResult, RawPosting

_logger = get_logger(__name__)

_API = "https://api.adzuna.com/v1/api/jobs"


class AdzunaCollector:
    source = Source.ADZUNA

    def __init__(self, *, app_id: str, app_key: str) -> None:
        self._app_id = app_id
        self._app_key = app_key

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        started = time.monotonic()
        fetched_at = utc_now()
        country = board.extra.get("country", "gb").lower()
        per_page = board.extra.get("results_per_page", "50")
        max_pages = int(board.extra.get("max_pages", "2"))

        postings: list[RawPosting] = []
        requests_made = 0
        truncated = False
        for page in range(1, max_pages + 1):
            params = {
                "app_id": self._app_id,
                "app_key": self._app_key,
                "what": board.token,
                "results_per_page": per_page,
                "content-type": "application/json",
            }
            if "where" in board.extra:
                params["where"] = board.extra["where"]
            data = get_json_checked(session, f"{_API}/{country}/search/{page}", params=params)
            if data is None:
                truncated = True
                break
            requests_made += 1
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise SourceSchemaChanged(f"adzuna: unexpected payload for {board.token!r}")
            for job in data["results"]:
                raw = _map_job(job, fetched_at)
                if raw is not None:
                    postings.append(raw)
            if not data["results"]:
                break

        return CollectResult(
            board=board,
            postings=tuple(postings),
            requests_made=requests_made,
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )


def _map_job(job: Any, fetched_at: datetime) -> RawPosting | None:
    if not isinstance(job, dict):
        return None
    company = job.get("company")
    employer = company.get("display_name") if isinstance(company, dict) else None
    job_id, title, url = job.get("id"), job.get("title"), job.get("redirect_url")
    if not job_id or not title or not url or not employer:
        _logger.info("collect_posting_skipped", source="adzuna", reason="missing_field")
        return None
    location = job.get("location")
    location_raw = location.get("display_name") if isinstance(location, dict) else None
    description = str(job.get("description") or "")
    title_str = str(title)
    return RawPosting(
        source=Source.ADZUNA,
        company_slug=slugify_employer(str(employer)),
        company_name=str(employer),
        source_job_id=str(job_id),
        url=str(url),
        title_raw=title_str,
        description_raw=description,
        location_raw=location_raw,
        department_raw=None,
        posted_at_raw=job.get("created"),
        payload=json.dumps(job).encode("utf-8"),
        fetched_at=fetched_at,
        content_hash=content_hash(title_str, description, location_raw),
    )
