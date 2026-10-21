"""Sheet rows ↔ application folders → `Application` — blueprint/wp/WP21-applications.md §3.

Within one employer (same `company_key`), every (row, folder) pair is scored on three signals:
the dates (the row's application date against the folder's own — a date-named folder, else
its screenshots' timestamp), the job title against the folder name, and the place ("NY" in a
folder against "USA (New York) NY" in the sheet). Pairs are taken best first, one to one. A row
whose best folder ties with another is left unpaired and reported, never guessed; a folder
holding several offers may serve two rows sent the same day.

What stays alone on either side still becomes an application — the sheet row without its
files, the folder with an estimated date — and is counted in the report.
"""

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from jobtracker.career.dossier import DossierEntry
from jobtracker.career.names import (
    company_key,
    name_leftover,
    place_agreement,
    places,
    title_tokens,
)
from jobtracker.career.sheet import SheetRow
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus
from jobtracker.core.models import Application, ApplicationEvent

_FOLDER_DATE = re.compile(r"^(\d{1,2})-(\d{1,2})-(\d{4})$")
_UNTITLED_FOLDERS = frozenset({"old", "older", "archive"})
_FAILED_INTERVIEW = re.compile(r"failed .*interview", re.IGNORECASE)
_STILL_OPEN = frozenset({"", "waiting for answer", "?"})
# A pair needs at least this much evidence to be taken; a folder serves a second row only on a
# same-week date.
_MIN_SCORE = 1
_SHARE_SCORE = 4


@dataclass(frozen=True)
class Ambiguity:
    row: SheetRow
    candidates: tuple[str, ...]  # the tied folders, root-relative


@dataclass
class Reconciliation:
    applications: list[Application] = field(default_factory=list)
    paired: int = 0
    shared: int = 0  # rows served by a folder already paired with another row
    sheet_only: int = 0
    folder_only: int = 0
    ambiguities: list[Ambiguity] = field(default_factory=list)
    unresolved_companies: list[str] = field(default_factory=list)  # no registry entry


def folder_date(entry: DossierEntry) -> tuple[date | None, bool]:
    """The folder's application date and whether it is estimated (a file timestamp)."""
    leaf = (entry.role or "").rsplit("/", 1)[-1]
    match = _FOLDER_DATE.match(leaf)
    if match:
        day, month, year = (int(part) for part in match.groups())
        try:
            return date(year, month, day), False
        except ValueError:
            return entry.first_seen, True  # "31-02-2025": a name, not a date
    return entry.first_seen, True


def folder_title(entry: DossierEntry) -> str | None:
    """The job title a folder name carries, if any ("Quant Dev NY"; not "Old", not a date)."""
    leaf = (entry.role or "").rsplit("/", 1)[-1]
    if not leaf or leaf.lower() in _UNTITLED_FOLDERS or _FOLDER_DATE.match(leaf):
        return None
    return leaf


def row_title_hint(row: SheetRow, entry: DossierEntry) -> str:
    """The row's job title, or what its employer name says beyond the folder's ("Google
    Gemini" against folder "Google"; "Aquatic Capital (Quant)")."""
    return row.title or name_leftover(row.company, entry.company)


def score(row: SheetRow, entry: DossierEntry) -> int | None:
    """Evidence that `row` and `entry` are the same application; None when they cannot be."""
    total = 0
    entry_day, _ = folder_date(entry)
    if row.applied.day and entry_day:
        gap = abs((row.applied.day - entry_day).days)
        if gap > 31:
            return None
        total += 4 if gap <= 2 else 3 if gap <= 10 else 1
    title = folder_title(entry)
    row_tokens = title_tokens(row_title_hint(row, entry))
    entry_tokens = title_tokens(title or "")
    if row_tokens and entry_tokens:
        overlap = len(row_tokens & entry_tokens)
        total += min(2 * overlap, 6) if overlap else -2
    agreement = place_agreement(places(row.location), places(title or ""))
    return total + (agreement or 0)


def _twins(left: SheetRow, right: SheetRow) -> bool:
    """Two rows nothing tells apart: whichever folder each gets, the result is the same."""
    return (left.company, left.title, left.location, left.applied, left.closed, left.reason) == (
        right.company,
        right.title,
        right.location,
        right.applied,
        right.closed,
        right.reason,
    )


def _status(row: SheetRow) -> tuple[ApplicationStatus, tuple[ApplicationEvent, ...]]:
    applied = ApplicationEvent(on_date=row.applied.day, status=ApplicationStatus.APPLIED)
    reason = row.reason.strip()
    waiting = reason.lower() == "waiting for answer"  # wins over a "?" rejection date
    if waiting or (reason.lower() in _STILL_OPEN and row.closed.day is None):
        return ApplicationStatus.APPLIED, (applied,)
    rejected = ApplicationEvent(
        on_date=row.closed.day, status=ApplicationStatus.REJECTED, reason=reason
    )
    if _FAILED_INTERVIEW.search(reason):
        interview = ApplicationEvent(on_date=None, status=ApplicationStatus.INTERVIEW)
        return ApplicationStatus.REJECTED, (applied, interview, rejected)
    return ApplicationStatus.REJECTED, (applied, rejected)


def _application_id(key: str, title: str | None, day: date | None, occurrence: int) -> str:
    payload = "\x1f".join(("import", key, (title or "").lower(), str(day or ""), str(occurrence)))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:26]


def _pair_group(
    rows: list[SheetRow], entries: list[DossierEntry], result: Reconciliation
) -> list[tuple[SheetRow | None, DossierEntry | None]]:
    scored = sorted(
        (
            (points, i, j)
            for i, row in enumerate(rows)
            for j, entry in enumerate(entries)
            if (points := score(row, entry)) is not None and points >= _MIN_SCORE
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    by_row: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for points, i, j in scored:
        by_row[i].append((points, j))
    row_taken: dict[int, int] = {}
    entry_taken: set[int] = set()
    blocked: set[int] = set()
    for points, i, j in scored:
        if i in row_taken or i in blocked or j in entry_taken:
            continue
        rivals = [k for p, k in by_row[i] if p == points and k != j and k not in entry_taken]
        twins = [
            r
            for r in range(len(rows))
            if r != i and r not in row_taken and r not in blocked and _twins(rows[r], rows[i])
        ]
        if rivals and len(twins) < len(rivals):
            blocked.add(i)
            tied = (entries[j].relative, *(entries[k].relative for k in rivals))
            result.ambiguities.append(Ambiguity(rows[i], tied))
            continue
        row_taken[i] = j
        entry_taken.add(j)
    pairs: list[tuple[SheetRow | None, DossierEntry | None]] = []
    for i, row in enumerate(rows):
        if i in row_taken:
            pairs.append((row, entries[row_taken[i]]))
            result.paired += 1
            continue
        shared = [j for p, j in by_row[i] if p >= _SHARE_SCORE and j in entry_taken]
        if i not in blocked and len(shared) == 1:
            pairs.append((row, entries[shared[0]]))
            result.shared += 1
            continue
        pairs.append((row, None))
        result.sheet_only += 1
    for j, entry in enumerate(entries):
        if j not in entry_taken:
            pairs.append((None, entry))
            result.folder_only += 1
    return pairs


def _build(
    key: str, slug: str | None, row: SheetRow | None, entry: DossierEntry | None, occurrence: int
) -> Application:
    if row is not None:
        status, events = _status(row)
        title = row.title or (folder_title(entry) if entry else None)
        applied_on, estimated = row.applied.day, False
        if applied_on is None and entry is not None:
            applied_on, estimated = folder_date(entry)
        company, location, reason, closed_on = (
            row.company,
            row.location or None,
            row.reason,
            row.closed.day,
        )
    else:
        assert entry is not None
        title = folder_title(entry)
        applied_on, estimated = folder_date(entry)
        company, location, reason, closed_on = entry.company, None, "", None
        status = ApplicationStatus.APPLIED
        events = (ApplicationEvent(on_date=applied_on, status=status),)
    return Application(
        application_id=_application_id(key, title, applied_on, occurrence),
        company=company,
        company_slug=slug,
        title=title,
        location=location,
        applied_on=applied_on,
        applied_on_estimated=estimated,
        closed_on=closed_on,
        status=status,
        reason=reason,
        posting_id=None,
        dossier=entry.relative if entry else None,
        origin=ApplicationOrigin.IMPORT,
        events=events,
    )


def reconcile(
    rows: list[SheetRow],
    entries: list[DossierEntry],
    *,
    aliases: Mapping[str, str],
    registry: Mapping[str, str],
) -> Reconciliation:
    """`registry` maps a `company_key` (aliases applied) to a registry slug."""
    result = Reconciliation()
    rows_by_key: dict[str, list[SheetRow]] = defaultdict(list)
    entries_by_key: dict[str, list[DossierEntry]] = defaultdict(list)
    for row in rows:
        rows_by_key[company_key(row.company, aliases)].append(row)
    for entry in entries:
        entries_by_key[company_key(entry.company, aliases)].append(entry)
    occurrences: dict[tuple[str, str | None, date | None], int] = defaultdict(int)
    unresolved: set[str] = set()
    for key in sorted(rows_by_key.keys() | entries_by_key.keys()):
        slug = registry.get(key)
        for pair in _pair_group(rows_by_key[key], entries_by_key[key], result):
            draft = _build(key, slug, *pair, occurrence=0)
            identity = (key, draft.title.lower() if draft.title else None, draft.applied_on)
            occurrence = occurrences[identity]
            occurrences[identity] += 1
            application = _build(key, slug, *pair, occurrence=occurrence) if occurrence else draft
            if slug is None:
                unresolved.add(application.company)
            result.applications.append(application)
    result.unresolved_companies = sorted(unresolved)
    return result
