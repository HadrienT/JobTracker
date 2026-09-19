"""The cascade orchestrator — blueprint/wp/WP03-normalize.md §1-2.

`normalize()` runs every stage and assembles a `Posting`. No stage may
raise (invariant I1): each one already degrades to an empty/`UNKNOWN` result
on its own, so this function itself needs no try/except to uphold that
invariant — it would be exactly the kind of `except: pass` interdit n°2
forbids if a stage's own contract weren't already total.
"""

import re
from datetime import UTC, datetime

from ulid import ULID

from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import Posting, RawPosting
from jobtracker.normalize.compensation import parse_compensation
from jobtracker.normalize.dedup import fingerprint
from jobtracker.normalize.language import parse_languages_required
from jobtracker.normalize.location import parse_location
from jobtracker.normalize.seniority import parse_seniority
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.normalize.techstack import parse_tech
from jobtracker.normalize.title import classify_role, clean_title
from jobtracker.normalize.visa import parse_visa

# Bumped whenever a parser or referential change should be replayed onto stored postings.
#   5: perks (budget, allowance, relocation) are not pay; "€1000" read whole; "$100-200K"
#   4: salary — company sizes ($14.6 billion) are not pay, labelled min/max, weekly and
#      period-less small figures are dropped, "between X and Y"
#   3: more cities in geo.yaml, and "Office" / "and" / "&" read in locations
#   2: quant trading / strategist / quantitative-risk titles are no longer "other"
NORMALIZE_VERSION = 5

_PHD_REQUIRED_RE = re.compile(
    r"\bphd\s+(?:is\s+)?required\b|\brequires?\s+a\s+phd\b|\bmust\s+have\s+a\s+phd\b",
    re.IGNORECASE,
)
_PHD_NOT_REQUIRED_RE = re.compile(
    r"\bphd\s+preferred\b|\bphd\s+(?:is\s+)?a\s+plus\b|\bno\s+phd\s+required\b|"
    r"\bphd\s+or\s+equivalent\b",
    re.IGNORECASE,
)

_ISO_DATE_FORMATS = ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d")


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in _ISO_DATE_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _detect_phd_required(description: str) -> bool:
    if _PHD_NOT_REQUIRED_RE.search(description):
        return False
    return bool(_PHD_REQUIRED_RE.search(description))


def normalize(
    raw: RawPosting, *, taxonomy: Taxonomy, geo: GeoIndex, hq_country: str | None = None
) -> Posting:
    """`RawPosting` -> `Posting`. Zero I/O (contract D8); never raises (I1)."""
    title = clean_title(raw.title_raw)
    role_family = classify_role(title, raw.description_raw, taxonomy=taxonomy)
    locations = parse_location(raw.location_raw, geo=geo, hq_country=hq_country)
    seniority, min_years = parse_seniority(title, raw.description_raw, taxonomy=taxonomy)
    primary_country = next((loc.country for loc in locations if loc.country), None)
    compensation = parse_compensation(raw.description_raw, country=primary_country)
    visa_status, visa_evidence = parse_visa(raw.description_raw, taxonomy=taxonomy)
    tech = parse_tech(raw.description_raw, taxonomy=taxonomy)
    languages_required = parse_languages_required(raw.description_raw, taxonomy=taxonomy)

    posted_at = _parse_date(raw.posted_at_raw)
    # A source that rewrites its own date to look fresh produces posted_at
    # *after* fetched_at, which is absurd — ignore it (blueprint/09-CONVENTIONS.md §3).
    if posted_at is not None and posted_at > raw.fetched_at:
        posted_at = None

    fp = fingerprint(raw.company_slug, title, primary_country, posted_at)

    return Posting(
        posting_id=str(ULID()),
        fingerprint=fp,
        source=raw.source,
        company_slug=raw.company_slug,
        source_job_id=raw.source_job_id,
        url=raw.url,
        title=title,
        title_raw=raw.title_raw,
        role_family=role_family,
        seniority=seniority,
        min_years=min_years,
        phd_required=_detect_phd_required(raw.description_raw),
        locations=locations,
        compensation=compensation,
        visa_sponsorship=visa_status,
        visa_evidence=visa_evidence,
        tech=tech,
        languages_required=languages_required,
        posted_at=posted_at,
        first_seen_at=raw.fetched_at,
        last_seen_at=raw.fetched_at,
        closes_at=None,
        content_hash=raw.content_hash,
        resolver_stage="rules",
        normalize_version=NORMALIZE_VERSION,
    )


__all__ = ["NORMALIZE_VERSION", "normalize"]
