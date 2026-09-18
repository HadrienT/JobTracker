"""What every aggregator collector shares — blueprint/wp/WP13-aggregators.md.

Two ideas matter more than the rest here:

- **A challenge page is a block, not an empty board.** Anti-bot systems very
  often answer `200` (or `405`) with an HTML page asking for a browser. Read as
  "zero postings" it would look exactly like a quiet market (P3); it must raise
  `SourceBlocked` so the breaker opens.
- **An employer is a `company_slug`.** Cross-source dedup keys on it
  (blueprint/03-INTERFACES.md §3.4), so "Jane Street Capital Ltd" seen at an
  aggregator has to land on the registry's `jane_street` or the same job shows up
  twice. Matching is deliberately exact-after-normalization: a wrong merge hides a
  posting, a missed one merely shows a duplicate and lists the employer in the
  discovery report — the second is the cheaper mistake.
"""

import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.robotparser import RobotFileParser

from jobtracker.collect.http import HttpSession
from jobtracker.core.errors import SourceBlocked, SourceSchemaChanged
from jobtracker.core.models import Board, RawPosting

_CHALLENGE_MARKERS = (
    "awswafcookiedomainlist",
    "gokuprops",
    "human verification",
    "just a moment",
    "cf-chl",
    "cf_chl_opt",
    "px-captcha",
    "are you a robot",
    "unusual traffic",
    "verify you are human",
    "enable javascript and cookies to continue",
)

_LEGAL_SUFFIXES = frozenset(
    {"ltd", "limited", "llc", "llp", "lp", "inc", "incorporated", "plc", "gmbh", "ag", "sa",
     "sas", "sarl", "bv", "nv", "corp", "corporation", "co", "company", "pte", "pty"}
)  # fmt: skip
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def raise_if_challenge(text: str, *, url: str) -> None:
    """`SourceBlocked` when `text` is an anti-bot interstitial rather than a listing."""
    head = text[:6000].lower()
    if any(marker in head for marker in _CHALLENGE_MARKERS):
        raise SourceBlocked(f"anti-bot challenge served for {url}")


def get_json_checked(
    session: HttpSession, url: str, *, params: Mapping[str, str] | None = None
) -> Any | None:
    """A JSON endpoint, with the challenge check `get_json` cannot make.

    `HttpSession.get_json` would turn an HTML challenge into `SourceSchemaChanged`;
    reading text first lets it be recognized for what it is. `None` means nothing
    was fetched (request budget spent), which the caller reports as `truncated`.
    """
    text = session.get_text(url, params=params)
    if not text:
        return None
    raise_if_challenge(text, url=url)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise SourceSchemaChanged(f"200 but body is not valid JSON: {url}") from exc


def normalize_name(name: str) -> str:
    """'Jane Street Ltd.' → 'jane street': accent-free, punctuation-free, legal suffixes dropped."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    text = text.replace(".", "")  # "S.A." must read as "sa", "J.P. Morgan" as "jp morgan"
    words = [w for w in _NON_ALNUM.sub(" ", text).split() if w not in _LEGAL_SUFFIXES]
    return " ".join(words)


def slugify_employer(name: str) -> str:
    """The registry's slug convention (`jane_street`) for an employer the registry lacks."""
    return normalize_name(name).replace(" ", "_") or "unknown"


class EmployerIndex:
    """The registry's companies, keyed by normalized name and by slug."""

    def __init__(self, boards: Iterable[Board]) -> None:
        self._by_key: dict[str, tuple[str, str]] = {}
        for board in boards:
            target = (board.company_slug, board.company_name)
            self._by_key.setdefault(normalize_name(board.company_name), target)
            self._by_key.setdefault(normalize_name(board.company_slug.replace("_", " ")), target)

    def resolve(self, name: str) -> tuple[str, str]:
        """(slug, name): the registry's when it is the same company, a derived slug otherwise."""
        hit = self._by_key.get(normalize_name(name))
        return hit if hit is not None else (slugify_employer(name), name)


def resolver(boards: Iterable[Board]) -> "EmployerResolver":
    return EmployerResolver(EmployerIndex(boards))


class EmployerResolver:
    """`AggregatorSetup.resolve_employer`: rewrites a raw posting's employer onto the registry's."""

    def __init__(self, index: EmployerIndex) -> None:
        self._index = index

    def __call__(self, raw: RawPosting) -> RawPosting:
        if raw.company_name is None:
            return raw
        slug, name = self._index.resolve(raw.company_name)
        return raw.model_copy(update={"company_slug": slug, "company_name": name})


class RobotsGate:
    """`robots.txt`, fetched once per host and honored — blueprint/11-SOURCES.md §6.

    A disallowed path raises `SourceBlocked`: the breaker then backs off instead of
    the collector retrying a request it was told not to make.
    """

    def __init__(self, session: HttpSession, *, user_agent: str = "*") -> None:
        self._session = session
        self._user_agent = user_agent
        self._parsers: dict[str, RobotFileParser] = {}

    def check(self, url: str) -> None:
        scheme_host = "/".join(url.split("/", 3)[:3])
        parser = self._parsers.get(scheme_host)
        if parser is None:
            parser = RobotFileParser()
            try:
                body = self._session.get_text(f"{scheme_host}/robots.txt")
            except Exception:
                body = ""
            parser.parse(body.splitlines())
            self._parsers[scheme_host] = parser
        if not parser.can_fetch(self._user_agent, url):
            raise SourceBlocked(f"robots.txt disallows {url}")
