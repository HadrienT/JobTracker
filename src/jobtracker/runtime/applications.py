"""Importing the application history — blueprint/wp/WP21-applications.md §3.

`career` reads and reconciles; this module does the side effects: the report, the copy of
each application folder under `data/career/applications/`, and the write to the database.
Dry-run unless asked otherwise, and idempotent: a second `--apply` changes nothing.
"""

import json
import shutil
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jobtracker.career.dossier import DossierEntry, DossierScan
from jobtracker.career.names import alias_map, company_key
from jobtracker.career.reconcile import Reconciliation, reconcile
from jobtracker.career.sheet import SheetParse
from jobtracker.core.db import transaction
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board
from jobtracker.store.applications import upsert_application

_logger = get_logger(__name__)


@dataclass(frozen=True)
class ImportOutcome:
    reconciliation: Reconciliation
    written: int
    purged: int  # imported rows the history no longer produces
    kept_stale: int  # ... kept anyway, because the user wrote a note on them
    files_copied: int


def registry_keys(boards: Iterable[Board], aliases: dict[str, str]) -> dict[str, str]:
    """`company_key` → registry slug, for every company of `configs/companies.yaml`."""
    return {company_key(board.company_name, aliases): board.company_slug for board in boards}


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
        return ImportOutcome(result, written=0, purged=0, kept_stale=0, files_copied=0)
    copied = _copy_files(dossier.entries, dossier_root, career_root / "applications")
    keep = {application.application_id for application in result.applications}
    with transaction(conn):
        for application in result.applications:
            upsert_application(conn, application)
        stale = conn.execute(
            "SELECT application_id, note FROM applications WHERE origin = 'import'"
        ).fetchall()
        gone = [row["application_id"] for row in stale if row["application_id"] not in keep]
        noted = {row["application_id"] for row in stale if row["note"]}
        purge = [application_id for application_id in gone if application_id not in noted]
        conn.executemany("DELETE FROM applications WHERE application_id = ?", [(i,) for i in purge])
    _logger.info(
        "applications_imported",
        written=len(result.applications),
        purged=len(purge),
        kept_stale=len(gone) - len(purge),
        files_copied=copied,
    )
    return ImportOutcome(
        result,
        written=len(result.applications),
        purged=len(purge),
        kept_stale=len(gone) - len(purge),
        files_copied=copied,
    )


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
