"""Applying to a collected posting — blueprint/wp/WP21-applications.md §2.2 and §4.

The feed's status select and the CLI (`jobtracker app add --posting`) both land here, so the two
paths cannot drift: the posting's application is found, linked or created, its history grows by
one step, and on creation the offer is archived as `offer.pdf` in the application's folder.

Rendering is the slow, fallible part (a headless browser), so it is split off: `track_posting`
writes the database and returns the PDF still to render, which the caller renders right away
(CLI) or after the response is sent (API). A failed render never undoes the application — it is
logged, and `jobtracker app pdf <id>` renders it again.
"""

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ulid import ULID

from jobtracker.career.feedlink import FeedPosting, link_postings
from jobtracker.career.offer import OfferSheet, location_label, sheet_for_posting, write_offer_pdf
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus
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
)
from jobtracker.store.postings import PostingRow, set_application_status
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
    candidates = [a for a in list_applications(conn) if a.posting_id is None and a.company_slug]
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
    create_application(conn, application)
    conn.commit()
    assert application.dossier is not None
    pending = PendingPdf(
        application.application_id,
        offer_sheet(conn, row, today),
        career_root / "applications" / application.dossier / OFFER_PDF,
    )
    return Tracked(application, created=True, linked=False, pdf=pending)
