"""Indeed — blueprint/wp/WP13-aggregators.md §3.4. Last, fragile, off by default.

**Not verified against the live site**: Indeed sits behind an aggressive anti-bot
and a failed probe risks the residential IP shared by everything else on this
machine (WP13 §warning), so this was written from the known page structure, not
tested against it. Its failure mode is designed to be loud rather than silent:

- a challenge page (any status) → `SourceBlocked`, never a zero-posting run;
- `robots.txt` disallowing the search path → `SourceBlocked`;
- the embedded job-cards JSON missing or reshaped → `SourceSchemaChanged`.

The listing embeds its results as `window.mosaic.providerData["mosaic-provider-jobcards"]`
— parsed as JSON, never through CSS selectors (they change with every redesign).
Requests go through `curl_cffi` TLS impersonation before anything heavier is
even considered (forbidden n°9).
"""

import json
import re
import time
from datetime import UTC, datetime
from typing import Any

from jobtracker.collect.aggregators.common import RobotsGate, raise_if_challenge, slugify_employer
from jobtracker.collect.http import HttpSession
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceSchemaChanged
from jobtracker.core.hashing import content_hash
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board, CollectResult, RawPosting

_logger = get_logger(__name__)

_MARKER = re.compile(r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*')


class IndeedCollector:
    source = Source.INDEED

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        started = time.monotonic()
        fetched_at = utc_now()
        domain = board.extra.get("domain", "www.indeed.com")
        url = f"https://{domain}/jobs"
        params = {"q": board.token, "l": board.extra.get("where", ""), "sort": "date"}

        RobotsGate(session).check(f"{url}?q={board.token}")
        html = session.get_text(url, params=params)
        if not html:
            return CollectResult(
                board=board,
                postings=(),
                requests_made=0,
                duration_ms=int((time.monotonic() - started) * 1000),
                truncated=True,
            )
        raise_if_challenge(html, url=url)

        results = _extract_results(html, domain=domain, board=board)
        postings = [r for job in results if (r := _map_job(job, domain, fetched_at)) is not None]
        return CollectResult(
            board=board,
            postings=tuple(postings),
            requests_made=2,  # robots.txt + the search page
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=False,
        )


def _extract_results(html: str, *, domain: str, board: Board) -> list[Any]:
    match = _MARKER.search(html)
    if match is None:
        raise SourceSchemaChanged(
            f"indeed: job-cards JSON not found on {domain} for {board.token!r}"
        )
    try:
        model, _ = json.JSONDecoder().raw_decode(html, match.end())
        results = model["metaData"]["mosaicProviderJobCardsModel"]["results"]
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceSchemaChanged(f"indeed: job-cards JSON reshaped on {domain}") from exc
    if not isinstance(results, list):
        raise SourceSchemaChanged(f"indeed: job-cards results is not a list on {domain}")
    return results


def _map_job(job: Any, domain: str, fetched_at: datetime) -> RawPosting | None:
    if not isinstance(job, dict):
        return None
    job_key, title, employer = job.get("jobkey"), job.get("title"), job.get("company")
    if not job_key or not title or not employer:
        _logger.info("collect_posting_skipped", source="indeed", reason="missing_field")
        return None
    pub = job.get("pubDate")
    posted = (
        datetime.fromtimestamp(pub / 1000, tz=UTC).isoformat() if isinstance(pub, int) else None
    )
    location_raw = job.get("formattedLocation")
    description = str(job.get("snippet") or "")
    title_str = str(title)
    return RawPosting(
        source=Source.INDEED,
        company_slug=slugify_employer(str(employer)),
        company_name=str(employer),
        source_job_id=str(job_key),
        url=f"https://{domain}/viewjob?jk={job_key}",
        title_raw=title_str,
        description_raw=description,
        location_raw=location_raw,
        department_raw=None,
        posted_at_raw=posted,
        payload=json.dumps(job).encode("utf-8"),
        fetched_at=fetched_at,
        content_hash=content_hash(title_str, description, location_raw),
    )
