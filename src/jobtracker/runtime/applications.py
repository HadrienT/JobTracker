"""Importing the application history — blueprint/wp/WP21-applications.md §3.

`career` reads and reconciles; this module does the side effects: the report, the copy of
each application folder under `data/career/applications/`, and the write to the database.
Dry-run unless asked otherwise, and idempotent: a second `--apply` changes nothing. An
application edited by hand since (status, note, link) is never rewritten nor purged.
"""

import json
import shutil
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from jobtracker.api.tracking import (
    OFFER_PDF,
    PendingPdf,
    new_application,
    offer_sheet,
    render_pending,
)
from jobtracker.career.dossier import DossierEntry, DossierScan
from jobtracker.career.feedlink import FeedPosting, link_postings
from jobtracker.career.names import alias_map, company_key
from jobtracker.career.offer import location_label
from jobtracker.career.reconcile import Reconciliation, reconcile
from jobtracker.career.sheet import SheetParse
from jobtracker.core.clock import utc_now
from jobtracker.core.db import transaction
from jobtracker.core.enums import ApplicationStatus, Triage
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board
from jobtracker.store.applications import (
    create_application,
    import_application,
    link_posting,
    list_applications,
    purge_stale_imports,
)
from jobtracker.store.postings import (
    PostingRow,
    get_posting_row,
    set_application_status,
    set_triage,
)

_logger = get_logger(__name__)


@dataclass(frozen=True)
class ImportOutcome:
    reconciliation: Reconciliation
    written: int
    kept_edited: int  # applications the user changed since the last import: left as they are
    purged: int  # imported rows the history no longer produces
    kept_stale: int  # ... kept anyway, because the user changed them
    files_copied: int


def registry_keys(boards: Iterable[Board], aliases: dict[str, str]) -> dict[str, str]:
    """`company_key` → registry slug, for every company of `configs/companies.yaml`. When
    several entries share a name (a firm's main board and its campus board), the first wins."""
    keys: dict[str, str] = {}
    for board in boards:
        keys.setdefault(company_key(board.company_name, aliases), board.company_slug)
    return keys


def _copy_files(entries: Iterable[DossierEntry], source: Path, target: Path) -> int:
    copied = 0
    for entry in entries:
        if (source / entry.relative).is_file():  # a screenshot left at the root
            names = [entry.relative]
        else:
            names = [f"{entry.relative}/{name}" for name in entry.files]
        for relative in [*names, *entry.inherited]:
            src, dst = source / relative, target / relative
            if dst.exists() and dst.stat().st_size == src.stat().st_size:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)  # keeps the timestamp: it dates the application
            copied += 1
    return copied


def import_history(
    conn: sqlite3.Connection,
    *,
    sheet: SheetParse,
    dossier: DossierScan,
    dossier_root: Path,
    aliases_config: dict[str, list[str]],
    boards: Iterable[Board],
    career_root: Path,
    apply: bool,
) -> ImportOutcome:
    aliases = alias_map(aliases_config)
    result = reconcile(
        sheet.rows, dossier.entries, aliases=aliases, registry=registry_keys(boards, aliases)
    )
    if not apply:
        return ImportOutcome(
            result, written=0, kept_edited=0, purged=0, kept_stale=0, files_copied=0
        )
    copied = _copy_files(dossier.entries, dossier_root, career_root / "applications")
    keep = {application.application_id for application in result.applications}
    with transaction(conn):
        written = sum(import_application(conn, a) for a in result.applications)
        purged, kept_stale = purge_stale_imports(conn, keep)
    outcome = ImportOutcome(
        result,
        written=written,
        kept_edited=len(result.applications) - written,
        purged=purged,
        kept_stale=kept_stale,
        files_copied=copied,
    )
    _logger.info(
        "applications_imported",
        written=outcome.written,
        kept_edited=outcome.kept_edited,
        purged=outcome.purged,
        kept_stale=outcome.kept_stale,
        files_copied=outcome.files_copied,
    )
    return outcome


def report_lines(sheet: SheetParse, dossier: DossierScan, outcome: ImportOutcome) -> list[str]:
    """The JSONL report: one object per thing a human should look at."""
    result = outcome.reconciliation
    records: list[dict[str, Any]] = []
    records += [
        {"kind": "sheet_issue", "line": i.line, "message": i.message, "cells": i.cells}
        for i in sheet.issues
    ]
    records += [
        {"kind": "skipped", "path": s.relative, "reason": s.reason} for s in dossier.skipped
    ]
    records += [
        {
            "kind": "ambiguous",
            "line": a.row.line,
            "company": a.row.company,
            "applied": str(a.row.applied.day),
            "folders": a.candidates,
        }
        for a in result.ambiguities
    ]
    for application in result.applications:
        if application.dossier is None:
            kind = "sheet_only"
        elif application.applied_on_estimated:
            kind = "folder_only"
        else:
            continue
        records.append(
            {
                "kind": kind,
                "company": application.company,
                "title": application.title,
                "applied": str(application.applied_on),
                "folder": application.dossier,
            }
        )
    records += [{"kind": "not_in_registry", "company": c} for c in result.unresolved_companies]
    return [json.dumps(record, ensure_ascii=False) for record in records]


@dataclass(frozen=True)
class FeedAdoption:
    """What became of the statuses set in the feed before applications existed (WP21 §2.2)."""

    linked: list[tuple[str, str]]  # (posting_id, application_id): the same job, already recorded
    created: list[str]  # posting_ids that became applications of their own
    triaged: list[str]  # `withdrawn` on a job never applied to: a "no", not an application
    ambiguous: list[tuple[str, tuple[str, ...]]]
    pdfs_failed: int


def adopt_feed_statuses(
    conn: sqlite3.Connection,
    *,
    career_root: Path,
    aliases_config: dict[str, list[str]],
    apply: bool,
    render: bool,
) -> FeedAdoption:
    """Turn every feed status that has no application behind it into one — or into what it
    really was. Withdrawn statuses matching no recorded application were the feed's "not for
    me" before triage existed: they become `triage = no`, and stay out of the feed."""
    rows = conn.execute(
        """
        SELECT uf.posting_id, uf.application_status, uf.status_updated_at, uf.triage
        FROM user_flags uf
        WHERE uf.application_status IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.posting_id = uf.posting_id)
        ORDER BY uf.status_updated_at, uf.posting_id
        """
    ).fetchall()
    legacy: list[tuple[PostingRow, ApplicationStatus, date, str | None]] = []
    for row in rows:
        posting = get_posting_row(conn, row["posting_id"])
        if posting is not None:
            day = date.fromisoformat(row["status_updated_at"][:10])
            legacy.append(
                (posting, ApplicationStatus(row["application_status"]), day, row["triage"])
            )
    feed = {
        p.posting_id: FeedPosting(
            posting_id=p.posting_id,
            company_slug=p.company_slug,
            company_name=p.company_name,
            title=p.title_raw,
            places=" ".join(location_label(loc) for loc in p.locations),
            day=day,
        )
        for p, _, day, _ in legacy
    }
    # Postings marked as applied claim their application first; a withdrawn one only gets
    # what is left — the twin offer you said no to must not take the one you applied to.
    aliases = alias_map(aliases_config)
    applications = list_applications(conn)
    withdrawn = {
        p.posting_id for p, status, _, _ in legacy if status is ApplicationStatus.WITHDRAWN
    }
    links = link_postings(
        [f for i, f in feed.items() if i not in withdrawn], applications, aliases=aliases
    )
    claimed = set(links.links.values())
    late = link_postings(
        [f for i, f in feed.items() if i in withdrawn],
        [a for a in applications if a.application_id not in claimed],
        aliases=aliases,
    )
    links.links.update(late.links)
    links.ambiguous.update(late.ambiguous)
    adoption = FeedAdoption(
        linked=sorted(links.links.items()),
        created=[],
        triaged=[],
        ambiguous=sorted(links.ambiguous.items()),
        pdfs_failed=0,
    )
    pending: list[PendingPdf] = []
    for posting, status, day, triage in legacy:
        if posting.posting_id in links.links or posting.posting_id in links.ambiguous:
            continue
        if status is ApplicationStatus.WITHDRAWN:
            adoption.triaged.append(posting.posting_id)
            if apply:
                if triage is None:
                    set_triage(conn, posting.posting_id, Triage.NO)
                set_application_status(conn, posting.posting_id, None)
            continue
        adoption.created.append(posting.posting_id)
        if apply:
            application = new_application(posting, status, day)
            create_application(conn, application)
            assert application.dossier is not None
            pending.append(
                PendingPdf(
                    application.application_id,
                    offer_sheet(conn, posting, day),
                    career_root / "applications" / application.dossier / OFFER_PDF,
                )
            )
    if apply:
        for posting_id, application_id in links.links.items():
            link_posting(conn, application_id, posting_id)
        conn.commit()
    failed = 0
    if render:
        today = utc_now().date()
        failed = sum(not render_pending(p, today=today) for p in pending)
    return FeedAdoption(
        adoption.linked,
        adoption.created,
        adoption.triaged,
        adoption.ambiguous,
        pdfs_failed=failed,
    )
