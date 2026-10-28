"""Companies with no ATS family of their own — blueprint/wp/WP06-collect-ats2.md §4.

Three ways in, tried in this order:

1. `_HANDLERS`: one function per company whose board needs code of its own. Each
   entry is a debt, and it is commented as one: why this particular company has no
   ATS family, and where its board actually lives.
2. The portal's own JSON endpoint (`extra.api`): the search call the career site
   itself makes, written down in the registry — its URL (and `extra.body` when it is
   a POST) with `{offset}`/`{page}`/`{size}` placeholders, where the postings sit in
   the answer (`extra.items`) and which of their fields are the id, title, location
   and public URL. No code per company, and one request lists a hundred postings. The
   description comes from the listing itself (`extra.description`), from a JSON detail
   endpoint (`extra.detail` + `extra.detail_description`), or, failing both, from the
   rendered posting page.
3. The rendered listing: a registry entry that names its listing page (`token`) and
   what a posting's link looks like (`extra.link`, a regex over absolute URLs) needs
   no code at all. The session behind `source: custom` renders pages in a headless
   browser (collect/browser.py), so this reads the DOM a visitor would see: every
   anchor matching `link` is a posting and the linked page is the description. A
   card's first line of text is the title and what follows it the location
   (`extra.title_line: 2` when the card leads with a badge, `extra.title: heading`
   to take the detail page's `<h1>` instead). `extra.pages` walks a paginated listing whose URL
   carries a `{page}` placeholder (`extra.page_start` if it does not count from 1,
   `extra.page_step` if the placeholder is an offset).

A description that costs a request of its own is only fetched for a title that could
matter (collect/prefilter.py) — a bank lists thousands of roles — and never twice: a
posting already stored is not opened again, the caller hands back what it knows
(`known`), exactly as it does for Workday — this module has no store access (contract
D5) and no memory between runs. The price is that an edit to a posting already stored
goes unseen until it is reposted.

Past ~20 hand-written `_HANDLERS`, that is itself a signal a whole ATS family was
missed (blueprint/11-SOURCES.md §3), not that this file should keep growing.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urldefrag, urljoin

from jobtracker.collect.http import BUDGET_EXHAUSTED, NOT_MODIFIED, HttpSession
from jobtracker.collect.prefilter import looks_relevant
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Source
from jobtracker.core.errors import (
    BoardNotFound,
    ConfigError,
    SourceSchemaChanged,
    SourceUnavailable,
)
from jobtracker.core.hashing import content_hash
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board, CollectResult, RawPosting

_logger = get_logger(__name__)

_HANDLERS: Mapping[str, Callable[[Board, HttpSession], CollectResult]] = {}

_MAX_PAGES = 400
# Anchor texts that label a button rather than name a posting; the detail page's
# own heading is the title then.
_GENERIC_ANCHOR_TEXT = re.compile(
    r"^(?:apply(?: now)?|learn more|read more|view(?: job| role| details| position)?|"
    r"details|more(?: info(?:rmation)?)?|see (?:job|role|more)|find out more|en savoir plus|"
    r"voir l['’]offre|postuler)\W*$",
    re.IGNORECASE,
)
_SKIPPED_ELEMENTS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "svg",
        "template",
        "title",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "button",
        "select",
    }
)
# Where a page keeps what it is about; when one is there, the rest is site chrome.
_MAIN_ELEMENTS = frozenset({"main", "article"})
_MIN_MAIN_TEXT = 200
_BLOCK_ELEMENTS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "tr", "section", "article", "h1", "h2", "h3", "h4", "h5"}
)
_DEFAULT_API_PAGE_SIZE = 100
# A total drifts while a listing is walked, and two ids can share a posting: short of
# this share of the announced total, the walk did not reach the end.
_API_COMPLETE_SHARE = 0.9
_API_PAGE_PLACEHOLDERS = ("{offset}", "{page}")
_FIELD_PLACEHOLDER = re.compile(r"\{([\w.]+)\}")
_SPACES = re.compile(r"[ \t\r\f\v\xa0]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")


@dataclass(frozen=True)
class KnownCustomPosting:
    title_raw: str
    location_raw: str | None
    description_raw: str


@dataclass
class CustomCollector:
    source: Source = field(default=Source.CUSTOM, init=False)
    # (company_slug, source_job_id) → what a previous cycle stored for that posting.
    known: Mapping[tuple[str, str], KnownCustomPosting] = field(default_factory=dict)

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        handler = _HANDLERS.get(board.company_slug)
        if handler is not None:
            return handler(board, session)
        if board.extra.get("api"):
            return _fetch_api_listing(board, session, self.known)
        if board.extra.get("link"):
            return _fetch_rendered_listing(board, session, self.known)
        raise BoardNotFound(
            f"custom: no handler registered for {board.company_slug!r} — "
            "the registry says source: custom but the entry has no extra.api, no "
            "extra.link, and collect/custom.py has no matching function"
        )


@dataclass(frozen=True)
class _Anchor:
    url: str
    # The anchor's text, one entry per text node: a card's title, location, team...
    parts: tuple[str, ...]

    @property
    def named_parts(self) -> tuple[str, ...]:
        return tuple(p for p in self.parts if not _GENERIC_ANCHOR_TEXT.match(p))


class _AnchorExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self._href: str | None = None
        self._parts: list[str] = []
        self.anchors: list[_Anchor] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._close_anchor()
        href = dict(attrs).get("href")
        if href:
            self._href = urldefrag(urljoin(self._base_url, href.strip())).url
            self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._close_anchor()

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def _close_anchor(self) -> None:
        if self._href is not None:
            parts = (_SPACES.sub(" ", p.replace("\n", " ")).strip() for p in self._parts)
            self.anchors.append(_Anchor(self._href, tuple(p for p in parts if p)))
        self._href = None
        self._parts = []


class _PageText(HTMLParser):
    """The readable text of a rendered page, and its first heading."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._main_depth = 0
        self._in_h1 = False
        self._parts: list[str] = []
        self._main_parts: list[str] = []
        self._h1: list[str] = []
        self.heading: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_ELEMENTS:
            self._skip_depth += 1
        elif tag in _MAIN_ELEMENTS:
            self._main_depth += 1
        elif tag in _BLOCK_ELEMENTS:
            self._append("\n")
        if tag == "h1" and self.heading is None:
            self._in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_ELEMENTS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _MAIN_ELEMENTS:
            self._main_depth = max(0, self._main_depth - 1)
        elif tag in _BLOCK_ELEMENTS:
            self._append("\n")
        if tag == "h1" and self._in_h1:
            self._in_h1 = False
            self.heading = _SPACES.sub(" ", " ".join(self._h1)).strip() or None

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self._h1.append(data)  # a posting's title often sits in the page <header>
        if not self._skip_depth:
            self._append(data)

    def _append(self, data: str) -> None:
        self._parts.append(data)
        if self._main_depth:
            self._main_parts.append(data)

    def text(self) -> str:
        main = _clean("".join(self._main_parts))
        return main if len(main) >= _MIN_MAIN_TEXT else _clean("".join(self._parts))


def _clean(text: str) -> str:
    out = _SPACES.sub(" ", unescape(text))
    out = "\n".join(line.strip() for line in out.split("\n"))
    return _BLANK_LINES.sub("\n\n", out).strip()


def _listing_urls(board: Board) -> list[str]:
    template = board.token
    if not template.startswith(("http://", "https://")):
        raise ConfigError(
            f"custom board {board.company_slug!r}: token must be the listing page URL"
        )
    try:
        pages = int(board.extra.get("pages", "1"))
        start = int(board.extra.get("page_start", "1"))
        step = int(board.extra.get("page_step", "1"))
    except ValueError as exc:
        raise ConfigError(
            f"custom board {board.company_slug!r}: extra.pages/page_start/page_step must be ints"
        ) from exc
    if "{page}" not in template:
        return [template]
    pages = max(1, min(pages, _MAX_PAGES))
    return [template.replace("{page}", str(start + i * step)) for i in range(pages)]


def _listing_page(session: HttpSession, url: str, *, first: bool) -> str:
    """One listing page, asked twice if need be. The first page failing is the board
    failing; a later one is a hiccup in a long walk."""
    try:
        return session.get_text(url)
    except SourceUnavailable:
        if first:
            raise
        return session.get_text(url)


def _matching_anchors(listing_url: str, html: str, pattern: re.Pattern[str]) -> list[_Anchor]:
    extractor = _AnchorExtractor(listing_url)
    extractor.feed(html)
    extractor.close()
    return [anchor for anchor in extractor.anchors if pattern.search(anchor.url) is not None]


def _new_postings(
    anchors: list[_Anchor], pattern: re.Pattern[str], found: Mapping[str, _Anchor]
) -> bool:
    return any(_job_id(pattern, anchor.url) not in found for anchor in anchors)


def _job_id(pattern: re.Pattern[str], url: str) -> str:
    match = pattern.search(url)
    if match is not None and match.groups() and match.group(1):
        return match.group(1)
    return url


def _fetch_rendered_listing(
    board: Board, session: HttpSession, known: Mapping[tuple[str, str], KnownCustomPosting]
) -> CollectResult:
    started = time.monotonic()
    fetched_at = utc_now()
    try:
        pattern = re.compile(board.extra["link"])
    except re.error as exc:
        raise ConfigError(
            f"custom board {board.company_slug!r}: extra.link is not a valid regex ({exc})"
        ) from exc

    requests_made = 0
    truncated = False
    found: dict[str, _Anchor] = {}
    for listing_url in _listing_urls(board):
        try:
            html = _listing_page(session, listing_url, first=not found)
        except SourceUnavailable:
            if not found:
                raise
            # A hundred pages in, one that will not load must not cost the pages already
            # read: keep them, and say the listing was not seen whole.
            _logger.warning(
                "custom_listing_page_failed", company_slug=board.company_slug, url=listing_url
            )
            truncated = True
            break
        if not html:
            truncated = True  # a spent budget reads as an empty body (collect/http.py)
            break
        requests_made += 1
        anchors = _matching_anchors(listing_url, html, pattern)
        if found and not _new_postings(anchors, pattern, found):
            # Past the first page, a page that adds nothing is the end of the listing — or
            # a render read too early: no card yet, or still the cards of the first page
            # while the script fetches the one asked for. Ending on the second would hide
            # every page after it, so the page gets one more look.
            html = session.get_text(listing_url)
            if not html:
                truncated = True
                break
            requests_made += 1
            anchors = _matching_anchors(listing_url, html, pattern)
        before = len(found)
        for anchor in anchors:
            job_id = _job_id(pattern, anchor.url)
            previous = found.get(job_id)
            # A card often links the same posting twice (title, then "Apply"): keep the named one.
            if previous is None or not previous.named_parts:
                found[job_id] = anchor
        if len(found) == before:
            break  # twice nothing new: past the end of the listing

    if not found and not truncated:
        # The page rendered and not one link looks like a posting. A company with no
        # opening is possible; a redesign that broke `extra.link` is the usual cause,
        # and the two must not look the same (blueprint/07-ERRORS-AND-LOGGING.md §4).
        _logger.warning(
            "custom_listing_no_match",
            company_slug=board.company_slug,
            url=board.token,
            link=board.extra["link"],
        )

    use_heading = board.extra.get("title") == "heading"
    try:
        title_at = int(board.extra.get("title_line", "1")) - 1
    except ValueError as exc:
        raise ConfigError(
            f"custom board {board.company_slug!r}: extra.title_line must be an int"
        ) from exc
    postings: list[RawPosting] = []
    for job_id, anchor in found.items():
        stored = known.get((board.company_slug, job_id))
        if stored is not None:
            title: str = stored.title_raw
            location: str | None = stored.location_raw
            description: str = stored.description_raw
        else:
            named = anchor.named_parts[max(title_at, 0) :]
            card_names_it = bool(named) and not use_heading
            if card_names_it and not looks_relevant(named[0]):
                _log_detail_skipped(board)
                title, location, description = named[0], ", ".join(named[1:]) or None, ""
            else:
                try:
                    detail_html = session.get_text(anchor.url)
                except (BoardNotFound, SourceUnavailable):
                    # This one posting's page is gone or slow, not the whole board.
                    _logger.info(
                        "collect_detail_not_found",
                        source="custom",
                        company_slug=board.company_slug,
                        url=anchor.url,
                    )
                    continue
                if not detail_html:
                    truncated = True  # budget spent: this posting waits for the next cycle
                    continue
                requests_made += 1
                page = _PageText()
                page.feed(detail_html)
                page.close()
                if card_names_it:
                    title = named[0]
                    location = ", ".join(named[1:]) or None
                else:
                    title = page.heading or (named[0] if named else "")
                    location = None
                description = page.text()
        if not title:
            _logger.info(
                "collect_posting_skipped",
                source="custom",
                company_slug=board.company_slug,
                reason="missing_required_field",
                url=anchor.url,
            )
            continue
        payload = {"url": anchor.url, "title": title, "location": location, "anchor": anchor.parts}
        postings.append(
            RawPosting(
                source=Source.CUSTOM,
                company_slug=board.company_slug,
                source_job_id=job_id,
                url=anchor.url,
                title_raw=title,
                description_raw=description,
                location_raw=location,
                department_raw=None,
                posted_at_raw=None,
                payload=json.dumps(payload).encode("utf-8"),
                fetched_at=fetched_at,
                content_hash=content_hash(title, description, location),
            )
        )

    return CollectResult(
        board=board,
        postings=tuple(postings),
        requests_made=requests_made,
        duration_ms=int((time.monotonic() - started) * 1000),
        truncated=truncated,
    )


def _log_detail_skipped(board: Board) -> None:
    _logger.info(
        "collect_detail_skipped",
        source="custom",
        company_slug=board.company_slug,
        reason="title_prefilter",
    )


def _dig(value: Any, path: str) -> list[Any]:
    """Every value a dotted path reaches. A list met on the way is walked through, so
    `locations.city` reads the city of each location; a digit picks one element, and
    `name=title` keeps the elements whose `name` is `title` (a list of key/value pairs).
    `.` is the value itself: an endpoint that answers with a bare list (d.vinci)."""
    current = [value]
    for key in path.split(".") if path != "." else []:
        wanted_key, is_filter, wanted_value = key.partition("=")
        reached: list[Any] = []
        for node in current:
            if isinstance(node, list) and key.isdigit():
                reached.extend(node[int(key) : int(key) + 1])
                continue
            for item in node if isinstance(node, list) else [node]:
                if not isinstance(item, dict):
                    continue
                if is_filter:
                    if str(item.get(wanted_key)) == wanted_value:
                        reached.append(item)
                elif key in item:
                    reached.append(item[key])
        current = reached
    leaves: list[Any] = []
    for node in current:
        leaves.extend(node if isinstance(node, list) else [node])
    return leaves


def _field(item: Any, paths: str, separator: str = ", ") -> str:
    """The text at one or several comma-separated paths, repeats dropped."""
    parts: list[str] = []
    for path in paths.split(","):
        for leaf in _dig(item, path.strip()):
            text = "" if leaf is None or isinstance(leaf, dict) else str(leaf).strip()
            if text and text not in parts:
                parts.append(text)
    return separator.join(parts)


def _fill(template: str, item: Any) -> str:
    return _FIELD_PLACEHOLDER.sub(lambda m: _field(item, m.group(1), ","), template)


@dataclass(frozen=True)
class _ApiSpec:
    """`extra.*` of a board listed through its portal's JSON endpoint."""

    api: str
    body: str | None
    size: int
    page_start: int
    items: str
    total: str | None
    job_id: str
    title: str
    location: str | None
    posted: str | None
    url: str
    description: str | None
    detail: str | None
    detail_description: str | None

    @property
    def paginated(self) -> bool:
        return any(p in self.api or p in (self.body or "") for p in _API_PAGE_PLACEHOLDERS)

    def page(self, index: int) -> tuple[str, Any]:
        values = {
            "{offset}": str(index * self.size),
            "{page}": str(self.page_start + index),
            "{size}": str(self.size),
        }
        url, body = self.api, self.body
        for placeholder, value in values.items():
            url = url.replace(placeholder, value)
            body = body.replace(placeholder, value) if body is not None else None
        return url, (json.loads(body) if body is not None else None)


def _api_spec(board: Board) -> _ApiSpec:
    extra = board.extra
    where = f"custom board {board.company_slug!r}"
    missing = [key for key in ("items", "id", "title", "url") if not extra.get(key)]
    if missing:
        raise ConfigError(f"{where}: extra.api needs extra.{', extra.'.join(missing)}")
    if extra.get("detail") and not extra.get("detail_description"):
        raise ConfigError(f"{where}: extra.detail needs extra.detail_description")
    try:
        spec = _ApiSpec(
            api=extra["api"],
            body=extra.get("body"),
            size=int(extra.get("size", _DEFAULT_API_PAGE_SIZE)),
            page_start=int(extra.get("page_start", "0")),
            items=extra["items"],
            total=extra.get("total"),
            job_id=extra["id"],
            title=extra["title"],
            location=extra.get("location"),
            posted=extra.get("posted"),
            url=extra["url"],
            description=extra.get("description"),
            detail=extra.get("detail"),
            detail_description=extra.get("detail_description"),
        )
        spec.page(0)
    except ValueError as exc:  # a non-integer size, or a body that is not JSON
        raise ConfigError(f"{where}: extra.size/page_start/body is malformed ({exc})") from exc
    if not spec.api.startswith(("http://", "https://")):
        raise ConfigError(f"{where}: extra.api must be the endpoint URL")
    return spec


def _list_api(
    board: Board, session: HttpSession, spec: _ApiSpec
) -> tuple[dict[str, Any], int, bool]:
    """Walk the endpoint's pages → (items by id, requests made, truncated)."""
    found: dict[str, Any] = {}
    requests_made = 0
    declared: int | None = None
    hit_page_cap = spec.paginated
    for index in range(_MAX_PAGES if spec.paginated else 1):
        url, body = spec.page(index)
        added = 0
        # A page that adds nothing is the end of the listing — or an endpoint that answered
        # short for once. Past the first page it is asked a second time before it counts.
        for _attempt in range(2 if index else 1):
            data = session.get_json(url) if body is None else session.post_json(url, json=body)
            if data is BUDGET_EXHAUSTED or data is NOT_MODIFIED:
                # Either way this cycle did not see the whole listing: nothing may be
                # deactivated on the strength of it.
                return found, requests_made, True
            requests_made += 1
            items = _dig(data, spec.items)
            total = _dig(data, spec.total)[:1] if spec.total else []
            if total and isinstance(total[0], int):
                declared = total[0]
            before = len(found)
            for item in items:
                job_id = _field(item, spec.job_id, "-") if isinstance(item, dict) else ""
                if job_id:
                    found.setdefault(job_id, item)
            added = len(found) - before
            if added:
                break
        # With a total announced, the walk goes as far as the total says: a page of
        # postings already seen (an endpoint whose order is not stable serves some) is not
        # the end. Without one, a page that adds nothing is all there is to go by.
        walked = (index + 1) * spec.size
        if (not added and (declared is None or not items)) or (
            declared is not None and (len(found) >= declared or walked >= declared)
        ):
            hit_page_cap = False
            break

    if not found:
        # An answer with no posting where the registry says they are: a company with no
        # opening, or an endpoint whose shape changed. Loud either way.
        _logger.warning(
            "custom_api_no_items", company_slug=board.company_slug, url=spec.api, items=spec.items
        )
    short = declared is not None and len(found) < declared * _API_COMPLETE_SHARE
    if short or hit_page_cap:
        # The endpoint announced more than the walk reached. Whatever stopped it, the
        # listing was not seen whole, and must not pass for one that was.
        _logger.warning(
            "custom_api_listing_short",
            company_slug=board.company_slug,
            declared=declared,
            listed=len(found),
        )
    return found, requests_made, short or hit_page_cap


def _api_description(
    board: Board, session: HttpSession, spec: _ApiSpec, item: Any, url: str
) -> tuple[str, int, bool]:
    """A description that is one request away → (text, requests made, budget spent)."""
    try:
        if spec.detail is not None and spec.detail_description is not None:
            data = session.get_json(_fill(spec.detail, item))
            if data is BUDGET_EXHAUSTED:
                return "", 0, True
            if data is NOT_MODIFIED:
                return "", 1, False
            return _field(data, spec.detail_description, "\n\n"), 1, False
        html = session.get_text(url)
    except (BoardNotFound, SourceUnavailable, SourceSchemaChanged):
        # This one posting's page is gone or slow, not the whole board: keep the posting.
        _logger.info(
            "collect_detail_not_found", source="custom", company_slug=board.company_slug, url=url
        )
        return "", 1, False
    if not html:
        return "", 0, True
    page = _PageText()
    page.feed(html)
    page.close()
    return page.text(), 1, False


def _fetch_api_listing(
    board: Board, session: HttpSession, known: Mapping[tuple[str, str], KnownCustomPosting]
) -> CollectResult:
    started = time.monotonic()
    fetched_at = utc_now()
    spec = _api_spec(board)
    found, requests_made, truncated = _list_api(board, session, spec)

    postings: list[RawPosting] = []
    for job_id, item in found.items():
        title = _field(item, spec.title, " ")
        url = _fill(spec.url, item)
        if not title or not url:
            _logger.info(
                "collect_posting_skipped",
                source="custom",
                company_slug=board.company_slug,
                reason="missing_required_field",
            )
            continue
        location = (_field(item, spec.location) or None) if spec.location else None
        stored = known.get((board.company_slug, job_id))
        if spec.description is not None:
            description = _field(item, spec.description, "\n\n")
        elif stored is not None:
            description = stored.description_raw
        elif not looks_relevant(title):
            _log_detail_skipped(board)
            description = ""
        else:
            description, detail_requests, budget_spent = _api_description(
                board, session, spec, item, url
            )
            requests_made += detail_requests
            truncated = truncated or budget_spent
        postings.append(
            RawPosting(
                source=Source.CUSTOM,
                company_slug=board.company_slug,
                source_job_id=job_id,
                url=url,
                title_raw=title,
                description_raw=description,
                location_raw=location,
                department_raw=None,
                posted_at_raw=(_field(item, spec.posted) or None) if spec.posted else None,
                payload=json.dumps(item, default=str).encode("utf-8"),
                fetched_at=fetched_at,
                content_hash=content_hash(title, description, location),
            )
        )

    return CollectResult(
        board=board,
        postings=tuple(postings),
        requests_made=requests_made,
        duration_ms=int((time.monotonic() - started) * 1000),
        truncated=truncated,
    )
