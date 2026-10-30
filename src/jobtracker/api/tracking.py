"""Applications, wherever they are made from — blueprint/wp/WP21-applications.md §2.2 and §4.

The feed's status select, the Applications tab and the CLI (`jobtracker app …`) all land here, so
the paths cannot drift. For a collected posting: its application is found, linked or created,
its history grows by one step, and on creation the offer is archived as `offer.pdf` in the
application's folder.

Rendering is the slow, fallible part (a headless browser), so it is split off: `track_posting`
writes the database and returns the PDF still to render, which the caller renders right away
(CLI) or after the response is sent (API). A failed render never undoes the application — it is
logged, and `jobtracker app pdf <id>` renders it again.

For an application made by hand (no posting), the same module builds it, archives the offer from
pasted text, and manages its folder: the files listed, attached, served — never outside it.
"""

import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ulid import ULID

from jobtracker.career.cvs import is_pdf, save_cv
from jobtracker.career.dossier import FileKind, classify
from jobtracker.career.feedlink import FeedPosting, link_postings
from jobtracker.career.offer import OfferSheet, location_label, sheet_for_posting, write_offer_pdf
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus, CvSource
from jobtracker.core.errors import RenderError
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Application, ApplicationEvent
from jobtracker.store.applications import (
    application_for_posting,
    create_application,
    delete_application,
    dossier_name,
    link_posting,
    list_applications,
    record_status,
    set_application_cv,
    update_application,
)
from jobtracker.store.cvs import add_cv, current_cv_id
from jobtracker.store.postings import PostingRow, get_posting_row, set_application_status
from jobtracker.store.search import get_description

_logger = get_logger(__name__)
OFFER_PDF = "offer.pdf"


@dataclass(frozen=True)
class PendingPdf:
    """An offer PDF to render: what goes in it, where it goes."""

    application_id: str
    sheet: OfferSheet
    target: Path


@dataclass(frozen=True)
class Tracked:
    application: Application | None  # None once tracking stopped
    created: bool
    linked: bool  # an application recorded before (by hand, or imported) was found and linked
    pdf: PendingPdf | None


def offer_sheet(conn: sqlite3.Connection, row: PostingRow, applied_on: date | None) -> OfferSheet:
    return sheet_for_posting(row, get_description(conn, row.posting_id), applied_on=applied_on)


def render_pending(pending: PendingPdf, *, today: date) -> bool:
    """Render one offer PDF; False (and a warning) when it could not be."""
    try:
        write_offer_pdf(pending.sheet, pending.target, archived_on=today)
    except RenderError as exc:
        _logger.warning("offer_pdf_failed", application_id=pending.application_id, error=str(exc))
        return False
    _logger.info("offer_pdf_written", application_id=pending.application_id)
    return True


def _find_recorded(
    conn: sqlite3.Connection, row: PostingRow, today: date, aliases: Mapping[str, str]
) -> Application | None:
    """An unlinked application at the same employer that is this posting: applied to by hand
    before the collector saw it, or imported from the history."""
    candidates = [a for a in list_applications(conn) if a.posting_id is None]
    posting = FeedPosting(
        posting_id=row.posting_id,
        company_slug=row.company_slug,
        company_name=row.company_name,
        title=row.title_raw,
        places=" ".join(location_label(loc) for loc in row.locations),
        day=today,
    )
    found = link_postings([posting], candidates, aliases=aliases).links.get(row.posting_id)
    return next((a for a in candidates if a.application_id == found), None)


def assume_current_cv(conn: sqlite3.Connection, application: Application) -> Application:
    """A new application, with the version in use until the user says otherwise (WP22 §5)."""
    cv_id = current_cv_id(conn)
    if cv_id is None:
        return application
    return application.model_copy(update={"cv_id": cv_id, "cv_source": CvSource.INFERRED})


def new_application(row: PostingRow, status: ApplicationStatus, today: date) -> Application:
    events = [ApplicationEvent(on_date=today, status=ApplicationStatus.APPLIED)]
    if status is not ApplicationStatus.APPLIED:
        events.append(ApplicationEvent(on_date=today, status=status))
    return Application(
        application_id=str(ULID()),
        company=row.company_name,
        company_slug=row.company_slug,
        title=row.title_raw,
        location=" · ".join(dict.fromkeys(filter(None, map(location_label, row.locations))))
        or None,
        applied_on=today,
        applied_on_estimated=False,
        closed_on=today
        if status in {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
        else None,
        status=status,
        reason="",
        posting_id=row.posting_id,
        dossier=dossier_name(today, row.company_name, row.title_raw),
        origin=ApplicationOrigin.FEED,
        events=tuple(events),
    )


def track_posting(
    conn: sqlite3.Connection,
    row: PostingRow,
    status: ApplicationStatus | None,
    *,
    today: date,
    career_root: Path,
    aliases: Mapping[str, str],
    origin: ApplicationOrigin = ApplicationOrigin.FEED,
) -> Tracked:
    """Set the posting's application status; commits. `None` stops tracking: an application
    the feed created is deleted (its files stay on disk), any other one is only unlinked."""
    current = application_for_posting(conn, row.posting_id)
    if status is None:
        if current is None:
            set_application_status(conn, row.posting_id, None)  # a flag from before WP21
        elif current.origin is ApplicationOrigin.FEED:
            delete_application(conn, current.application_id)
        else:
            link_posting(conn, current.application_id, None)
        conn.commit()
        return Tracked(None, created=False, linked=False, pdf=None)

    linked = False
    if current is None and (recorded := _find_recorded(conn, row, today, aliases)) is not None:
        link_posting(conn, recorded.application_id, row.posting_id)
        current, linked = recorded, True
    if current is not None:
        if current.status is not status:
            record_status(conn, current.application_id, status, on_date=today)
        conn.commit()
        return Tracked(
            application_for_posting(conn, row.posting_id), created=False, linked=linked, pdf=None
        )

    application = new_application(row, status, today)
    if origin is not ApplicationOrigin.FEED:
        application = application.model_copy(update={"origin": origin})
    create_application(conn, assume_current_cv(conn, application))
    conn.commit()
    assert application.dossier is not None
    pending = PendingPdf(
        application.application_id,
        offer_sheet(conn, row, today),
        career_root / "applications" / application.dossier / OFFER_PDF,
    )
    return Tracked(application, created=True, linked=False, pdf=pending)


# --- applications made by hand ---------------------------------------------------------------

_UNSAFE_NAME = re.compile(r"[^\w.() +-]+")


def manual_application(
    *,
    company: str,
    title: str,
    location: str | None,
    applied_on: date,
    status: ApplicationStatus,
    note: str,
    company_slug: str | None,
    origin: ApplicationOrigin,
    posting_id: str | None = None,
) -> Application:
    """An application typed in: no posting behind it (or one found by its URL)."""
    events = [ApplicationEvent(on_date=applied_on, status=ApplicationStatus.APPLIED)]
    if status is not ApplicationStatus.APPLIED:
        events.append(ApplicationEvent(on_date=applied_on, status=status))
    return Application(
        application_id=str(ULID()),
        company=company,
        company_slug=company_slug,
        title=title,
        location=location,
        applied_on=applied_on,
        applied_on_estimated=False,
        closed_on=applied_on
        if status in {ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
        else None,
        status=status,
        reason="",
        posting_id=posting_id,
        dossier=dossier_name(applied_on, company, title),
        origin=origin,
        note=note,
        events=tuple(events),
    )


def manual_sheet(application: Application, text: str, url: str | None) -> OfferSheet:
    """The offer PDF of an application typed in, from the offer's text pasted by the user."""
    return OfferSheet(
        title=application.title or "(no title)",
        company=application.company,
        description=text,
        locations=(application.location,) if application.location else (),
        url=url,
        applied_on=application.applied_on,
    )


def folder_of(career_root: Path, application: Application) -> Path | None:
    if application.dossier is None:
        return None
    return career_root / "applications" / application.dossier


def ensure_folder(conn: sqlite3.Connection, career_root: Path, application: Application) -> Path:
    """The application's folder, given one if it had none (an imported row without files)."""
    folder = folder_of(career_root, application)
    if folder is None or folder.is_file():
        name = dossier_name(
            application.applied_on or utc_now().date(), application.company, application.title
        )
        update_application(conn, application.application_id, dossier=name)
        conn.commit()
        folder = career_root / "applications" / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def offer_pdf_for(
    conn: sqlite3.Connection,
    career_root: Path,
    application: Application,
    *,
    text: str | None,
    url: str | None,
) -> PendingPdf | None:
    """The offer PDF to (re)render: from pasted text if given, else from the linked posting;
    None when there is neither."""
    sheet = None
    if text:
        sheet = manual_sheet(application, text, url)
    elif application.posting_id is not None:
        row = get_posting_row(conn, application.posting_id)
        if row is not None:
            sheet = offer_sheet(conn, row, application.applied_on)
    if sheet is None:
        return None
    folder = ensure_folder(conn, career_root, application)
    return PendingPdf(application.application_id, sheet, folder / OFFER_PDF)


@dataclass(frozen=True)
class AppFile:
    name: str
    relative: str  # under `career_root / "applications"`, "/"-separated
    kind: FileKind
    size: int


def _listed(folder: Path, root: Path) -> list[AppFile]:
    paths = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.endswith(".part"))
    names = frozenset(p.name for p in paths)
    return [
        AppFile(p.name, p.relative_to(root).as_posix(), classify(p, names), p.stat().st_size)
        for p in paths
        if not p.name.startswith(".")
    ]


def application_files(career_root: Path, application: Application) -> list[AppFile]:
    """The application's own files, then a CV shared from a parent folder (the history kept one
    CV above several job folders) — never a sibling application's files."""
    root = career_root / "applications"
    target = folder_of(career_root, application)
    if target is None or not target.exists():
        return []
    if target.is_file():
        return [AppFile(target.name, target.relative_to(root).as_posix(), FileKind.OFFER,
                        target.stat().st_size)]  # fmt: skip
    files = _listed(target, root)
    parent = target.parent
    while parent != root and root in parent.parents:
        shared = _listed(parent, root)
        if not any(f.kind is FileKind.OFFER for f in shared):
            files += [f for f in shared if f.kind is FileKind.CV]
        parent = parent.parent
    return files


def resolve_file(career_root: Path, application: Application, relative: str) -> Path | None:
    """A file of this application, by its listed path — anything else is None."""
    if relative not in {f.relative for f in application_files(career_root, application)}:
        return None
    return career_root / "applications" / relative


def safe_file_name(name: str) -> str:
    cleaned = _UNSAFE_NAME.sub("_", Path(name.replace("\\", "/")).name).strip(" .")
    if not cleaned:
        raise ValueError(f"not a usable file name: {name!r}")
    return cleaned


def register_cv(
    conn: sqlite3.Connection,
    career_root: Path,
    data: bytes,
    file_name: str,
    *,
    label: str | None = None,
    pinned: bool = True,
) -> str:
    """Into the registry, by content; a CV already there stays as named. No commit."""
    if not is_pdf(data):
        raise ValueError(f"not a PDF: {file_name!r}")
    cv_id = save_cv(career_root, data)
    add_cv(
        conn,
        cv_id,
        label=label or Path(file_name).stem,
        file_name=file_name,
        size=len(data),
        pinned=pinned,
        created_at=utc_now(),
    )
    return cv_id


def adopt_attached_cv(
    conn: sqlite3.Connection, career_root: Path, application: Application, path: Path
) -> bool:
    """A CV attached to an application by hand is the one it was sent with: the registry learns
    it, unless the user had already chosen. It is written for this offer, so it is no version."""
    if application.cv_source is CvSource.CONFIRMED or path.suffix.lower() != ".pdf":
        return False
    if classify(path, frozenset(p.name for p in path.parent.iterdir())) is not FileKind.CV:
        return False
    data = path.read_bytes()
    if not is_pdf(data):
        return False
    label = f"{application.company} — {application.title or 'application'}"
    cv_id = register_cv(conn, career_root, data, path.name, label=label[:200], pinned=False)
    set_application_cv(conn, application.application_id, cv_id)
    conn.commit()
    return True


def store_file(folder: Path, name: str, data: bytes) -> Path:
    """Write an attached file into the folder; an existing name gets a numbered twin."""
    target = folder / safe_file_name(name)
    counter = 2
    while target.exists():
        target = folder / f"{Path(safe_file_name(name)).stem}-{counter}{target.suffix}"
        counter += 1
    target.write_bytes(data)
    return target
