"""eFinancialCareers — blueprint/wp/WP13-aggregators.md §3.3.

The site is an Angular app that embeds the JSON answer of its own search API in
the page. Rather than scrape that page's HTML (unstable, and behind an AWS WAF
challenge for a plain client), this calls the same search API directly:
`job-search-ui.efinancialcareers.com/v1/efc/jobs/search`, which answers JSON with
a normal client. Shape verified against the live response on 2026-09-18.

Many eFC postings are from recruitment agencies rather than the employer itself
(their `companyName` is the agency) — those are kept, and show up honestly as
employers in the discovery report.
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

_SEARCH_URL = "https://job-search-ui.efinancialcareers.com/v1/efc/jobs/search"
_SITE = "https://www.efinancialcareers.com"
_CURRENCY = {"GB": "GBP", "US": "USD", "SG": "SGD", "HK": "HKD"}


class EfcCollector:
    source = Source.EFC

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        started = time.monotonic()
        fetched_at = utc_now()
        country = board.extra.get("country", "GB").upper()
        page_size = int(board.extra.get("page_size", "15"))
        max_pages = int(board.extra.get("max_pages", "2"))

        postings: list[RawPosting] = []
        requests_made = 0
        truncated = False
        for page in range(1, max_pages + 1):
            data = get_json_checked(
                session,
                _SEARCH_URL,
                params={
                    "q": board.token,
                    "countryCode2": country,
                    "radius": "50",
                    "radiusUnit": "mi",
                    "page": str(page),
                    "pageSize": str(page_size),
                    "currencyCode": _CURRENCY.get(country, "EUR"),
                    "culture": "en",
                    "includeRemote": "false",
                    "includeUnspecifiedSalary": "true",
                },
            )
            if data is None:
                truncated = True
                break
            requests_made += 1
            if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                raise SourceSchemaChanged(
                    f"efinancialcareers: unexpected payload for {board.token!r}"
                )
            for job in data["data"]:
                raw = _map_job(job, fetched_at)
                if raw is not None:
                    postings.append(raw)
            meta = data.get("meta")
            page_count = meta.get("pageCount") if isinstance(meta, dict) else None
            if not data["data"] or (isinstance(page_count, int) and page >= page_count):
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
    job_id, title, path, employer = (
        job.get("id"),
        job.get("title"),
        job.get("detailsPageUrl"),
        job.get("companyName"),
    )
    if not job_id or not title or not path or not employer:
        _logger.info("collect_posting_skipped", source="efinancialcareers", reason="missing_field")
        return None
    location = job.get("jobLocation")
    location_raw = location.get("displayName") if isinstance(location, dict) else None
    description = str(job.get("description") or job.get("summary") or "")
    title_str = str(title)
    return RawPosting(
        source=Source.EFC,
        company_slug=slugify_employer(str(employer)),
        company_name=str(employer),
        source_job_id=str(job_id),
        url=f"{_SITE}{path}",
        title_raw=title_str,
        description_raw=description,
        location_raw=location_raw,
        department_raw=None,
        posted_at_raw=job.get("postedDate"),
        payload=json.dumps(job).encode("utf-8"),
        fetched_at=fetched_at,
        content_hash=content_hash(title_str, description, location_raw),
    )
