"""Link past applications to the CV registry — blueprint/wp/WP22-cvs.md §3.

The CV of each application is read off its folder, by content; a CV of a parent folder counts
only when the folder has none of its own (it was kept for older siblings). Two kinds of folder
are not guessed: one holding several different CVs is reported as ambiguous, one holding none
stays unlinked. Only applications without a CV are looked at, so a choice made by hand is never
overwritten and the backfill can run again after an import. Files stay where they are.
"""

import sqlite3
from collections import defaultdict
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from pathlib import Path

from jobtracker.api.tracking import application_files
from jobtracker.career.cvs import cv_id_of, is_pdf, save_cv
from jobtracker.career.dossier import FileKind
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import CvSource
from jobtracker.core.models import Application
from jobtracker.store.applications import infer_application_cv, list_applications
from jobtracker.store.cvs import add_cv


@dataclass(frozen=True)
class Link:
    application: Application
    cv_id: str
    file_name: str
    source: CvSource


@dataclass
class CvPlan:
    links: list[Link] = field(default_factory=list)
    contents: dict[str, bytes] = field(default_factory=dict)
    ambiguous: dict[str, tuple[str, ...]] = field(default_factory=dict)  # application_id → files
    unreadable: dict[str, tuple[str, ...]] = field(default_factory=dict)  # named CV, not a PDF
    without_cv: list[str] = field(default_factory=list)


def _title(application: Application) -> str:
    return f"{application.company} — {application.title or 'application'}"


def plan_backfill(
    conn: sqlite3.Connection, career_root: Path, *, inferred_names: Collection[str] = ()
) -> CvPlan:
    """`inferred_names`: files put in a folder after the fact, from memory or from the dates,
    not kept when the application was sent."""
    plan = CvPlan()
    for application in list_applications(conn):
        if application.cv_id is not None:
            continue
        files = [
            f
            for f in application_files(career_root, application)
            if f.kind is FileKind.CV and f.name.lower().endswith(".pdf")
        ]
        own = [f for f in files if f.relative.startswith(f"{application.dossier}/")]
        by_id: dict[str, str] = {}
        rejected: list[str] = []
        for file in own or files:
            data = (career_root / "applications" / file.relative).read_bytes()
            if not is_pdf(data):
                rejected.append(file.name)
                continue
            plan.contents.setdefault(cv_id_of(data), data)
            by_id.setdefault(cv_id_of(data), file.name)
        if rejected:
            plan.unreadable[application.application_id] = tuple(rejected)
        if len(by_id) > 1:
            plan.ambiguous[application.application_id] = tuple(by_id.values())
        elif by_id:
            ((cv_id, name),) = by_id.items()
            source = CvSource.INFERRED if name in inferred_names else CvSource.CONFIRMED
            plan.links.append(Link(application, cv_id, name, source))
        else:
            plan.without_cv.append(application.application_id)
    return plan


def _first_use(links: list[Link]) -> datetime:
    days = [link.application.applied_on for link in links if link.application.applied_on]
    return datetime.combine(min(days), time.min, UTC) if days else utc_now()


def apply_backfill(conn: sqlite3.Connection, career_root: Path, plan: CvPlan) -> int:
    """Store each distinct CV and write the links. A CV sent more than once is a version; one
    sent once was written for that offer, and is named after it. Returns the CVs stored."""
    by_cv: dict[str, list[Link]] = defaultdict(list)
    for link in plan.links:
        by_cv[link.cv_id].append(link)
    for cv_id, links in by_cv.items():
        data = plan.contents[cv_id]
        assert save_cv(career_root, data) == cv_id
        version = len(links) > 1
        add_cv(
            conn,
            cv_id,
            label=Path(links[0].file_name).stem if version else _title(links[0].application),
            file_name=links[0].file_name,
            size=len(data),
            pinned=version,
            created_at=_first_use(links),
        )
    for link in plan.links:
        infer_application_cv(conn, link.application.application_id, link.cv_id, link.source)
    conn.commit()
    return len(by_cv)
