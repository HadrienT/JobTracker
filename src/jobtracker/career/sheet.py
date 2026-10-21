"""The application spreadsheet, exported as CSV — blueprint/wp/WP21-applications.md §3.

The sheet is laid out like a calendar, not a table: blocks of columns side by side (one per
period), each block a header row (`Country, Company, [Job,] Application date, Rejection date,
Reason`), month names on rows of their own, and per-block totals scattered below. The layout
changes partway down: a new header row starts a new set of blocks, possibly with other columns.

So the parser follows the header rows. Each one fixes where the blocks start and which column
means what, until the next. A row inside a block is an application, a month marker, a totals
row, or blank; anything else is reported as an issue rather than guessed.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date

_MONTHS = frozenset(
    {
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    }
)  # fmt: skip
_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_COUNT = re.compile(r"^\d+$")
_SPACES = re.compile(r"\s+")

# Header cell → field. Unknown header cells are ignored.
_HEADER_FIELDS = {
    "country": "location",
    "company": "company",
    "job": "title",
    "application date": "applied",
    "rejection date": "closed",
    "reason": "reason",
}


@dataclass(frozen=True)
class SheetDate:
    """A date cell: a day, unknown (`?` or blank), or unreadable (`raw` kept for the report)."""

    day: date | None
    unknown_marked: bool = False  # the user wrote "?": they know there was a date


@dataclass(frozen=True)
class SheetRow:
    line: int  # 1-based line in the CSV, for the report
    block: int  # 0-based block index within its header's layout
    location: str
    company: str
    title: str | None
    applied: SheetDate
    closed: SheetDate
    reason: str


@dataclass(frozen=True)
class SheetIssue:
    line: int
    block: int
    message: str
    cells: tuple[str, ...]


@dataclass
class SheetParse:
    rows: list[SheetRow] = field(default_factory=list)
    issues: list[SheetIssue] = field(default_factory=list)


def _clean(cell: str) -> str:
    return _SPACES.sub(" ", cell).strip()


def _layout(cells: list[str]) -> list[dict[str, int]] | None:
    """Blocks of a header row: per block, field → column index. None if not a header row."""
    starts = [i for i, cell in enumerate(cells) if _clean(cell).lower() == "country"]
    if not starts:
        return None
    blocks = []
    for start in starts:
        fields: dict[str, int] = {}
        for i in range(start, len(cells)):
            name = _clean(cells[i]).lower()
            if not name or (i > start and name == "country"):
                break
            if name in _HEADER_FIELDS:
                fields[_HEADER_FIELDS[name]] = i
        blocks.append(fields)
    return blocks


def _parse_date(cell: str) -> SheetDate | None:
    """None if the cell is neither empty, `?`, nor a `dd/mm/yyyy` day."""
    text = _clean(cell)
    if not text:
        return SheetDate(day=None)
    if text == "?":
        return SheetDate(day=None, unknown_marked=True)
    match = _DATE.match(text)
    if match is None:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return SheetDate(day=date(year, month, day))
    except ValueError:
        return None


def parse_sheet(text: str) -> SheetParse:
    result = SheetParse()
    layout: list[dict[str, int]] = []
    for line, cells in enumerate(csv.reader(io.StringIO(text)), start=1):
        header = _layout(cells)
        if header is not None:
            layout = header
            continue
        for block, fields in enumerate(layout):
            span = sorted(fields.values())
            values = {
                name: _clean(cells[index]) if index < len(cells) else ""
                for name, index in fields.items()
            }
            raw = tuple(_clean(cells[i]) for i in range(span[0], span[-1] + 1) if i < len(cells))
            filled = [value for value in raw if value]
            if not filled:
                continue
            if len(filled) == 1 and filled[0].lower() in _MONTHS:
                continue
            if all(_COUNT.match(value) for value in filled):
                continue  # the per-block totals
            if not values.get("company"):
                result.issues.append(SheetIssue(line, block, "no company", raw))
                continue
            applied = _parse_date(values.get("applied", ""))
            closed = _parse_date(values.get("closed", ""))
            if applied is None or closed is None:
                result.issues.append(SheetIssue(line, block, "unreadable date", raw))
                continue
            result.rows.append(
                SheetRow(
                    line=line,
                    block=block,
                    location=values.get("location", ""),
                    company=values["company"],
                    title=values.get("title") or None,
                    applied=applied,
                    closed=closed,
                    reason=values.get("reason", ""),
                )
            )
    return result
