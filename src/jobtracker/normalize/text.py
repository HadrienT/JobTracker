"""Readable text out of a job description — zero I/O, deterministic.

Sources disagree on what a description is. Ashby and Lever give plain text; Greenhouse gives
HTML that is *entity-escaped* (`&lt;p&gt;Hello&lt;/p&gt;`), so it is HTML inside a string that
looks like text; some aggregators give real HTML. The UI shows the description as text and the
normalizer's regexes read it, so both want the same thing: paragraphs, bullet lists, no tags,
no entities. Plain text passes through untouched.
"""

import html
import re
from html.parser import HTMLParser

# Something that is worth parsing: a tag, or an entity that would hide one.
_LOOKS_LIKE_MARKUP = re.compile(r"</?[a-zA-Z][^>]*>|&lt;|&gt;|&amp;|&nbsp;|&#\d+;|&#x[0-9a-fA-F]+;")
_ESCAPED_TAG = re.compile(r"&lt;/?[a-zA-Z]")
_MAX_UNESCAPE_PASSES = 3  # bounded: a hostile string must not make this loop

_BLOCK_TAGS = frozenset(
    {"p", "div", "section", "article", "header", "footer", "ul", "ol", "table", "tr", "h1", "h2",
     "h3", "h4", "h5", "h6", "blockquote", "pre"}
)  # fmt: skip
_SKIPPED_TAGS = frozenset({"script", "style", "head"})

_SPACES = re.compile(r"[^\S\n]+")  # any whitespace but the newline
_BLANK_RUNS = re.compile(r"\n{3,}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1
        elif tag == "br":
            self._parts.append("\n")
        elif tag == "li":
            self._parts.append("\n• ")
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(raw: str) -> str:
    """`raw` as readable text. Idempotent, and the identity on text that holds no markup."""
    if not raw or not _LOOKS_LIKE_MARKUP.search(raw):
        return raw

    text = raw
    for _ in range(_MAX_UNESCAPE_PASSES):
        if not _ESCAPED_TAG.search(text):
            break
        text = html.unescape(text)

    extractor = _TextExtractor()
    extractor.feed(text)
    extractor.close()
    out = extractor.text().replace("\xa0", " ")
    out = _SPACES.sub(" ", out)
    out = "\n".join(line.strip() for line in out.split("\n"))
    return _BLANK_RUNS.sub("\n\n", out).strip()
