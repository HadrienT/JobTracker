"""Two hashes not to confuse — blueprint/wp/WP01-core.md §2.

``content_hash`` is sensitive to the smallest change in the raw text: it
detects that a posting *changed*, to avoid rescoring it for nothing.
``fingerprint`` is deliberately insensitive to noise: it is how two sources
advertising the same job get merged — see blueprint/03-INTERFACES.md §3.4.
"""

import hashlib
import re
from datetime import UTC, datetime

# Mirrors the default `dedup_window_days` of configs/sources.yaml
# (blueprint/06-CONFIG.md §4). The public signature of `fingerprint` is fixed
# by blueprint/03-INTERFACES.md §3.2/§3.4 and takes no window argument, so the
# window cannot be threaded through as a parameter without renegotiating that
# contract.
_DEDUP_WINDOW_DAYS = 14

_PARENTHESIZED = re.compile(r"[(\[][^)\]]*[)\]]")
_GENDER_NOISE = re.compile(r"\b[fhmw]/[fhmwx](?:/[dx])?\b", re.IGNORECASE)
_START_YEAR_NOISE = re.compile(
    r"\b(?:19|20)\d{2}\s*(?:start|intake|cohort)\b|\bstart(?:ing)?\s*(?:19|20)\d{2}\b",
    re.IGNORECASE,
)
_REQ_CODE_NOISE = re.compile(r"\b(?:req|ref|job)[-_ ]?#?\d+\b", re.IGNORECASE)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def content_hash(title: str, description: str, location: str | None) -> str:
    """Hash the raw content of a posting — changes on the smallest edit."""
    payload = "\x1f".join((title, description, location or ""))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clean_title_for_fingerprint(title: str) -> str:
    text = title.lower()
    text = _PARENTHESIZED.sub(" ", text)
    text = _GENDER_NOISE.sub(" ", text)
    text = _START_YEAR_NOISE.sub(" ", text)
    text = _REQ_CODE_NOISE.sub(" ", text)
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


def fingerprint(
    company_slug: str,
    title: str,
    country: str | None,
    posted_at: datetime | None,
) -> str:
    """Deduplication key across sources — see blueprint/03-INTERFACES.md §3.4."""
    parts = [company_slug.lower(), _clean_title_for_fingerprint(title), (country or "??").upper()]
    if posted_at is not None:
        bucket = int(posted_at.astimezone(UTC).timestamp() // (_DEDUP_WINDOW_DAYS * 86400))
        parts.append(str(bucket))
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
