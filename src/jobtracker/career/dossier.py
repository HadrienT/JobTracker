"""The folder of past applications — blueprint/wp/WP21-applications.md §3.

The user kept one folder per company, one sub-folder per job (`Tower Research Capital/Quant
Dev NY/`), holding screenshots of the offer (`1.png`, `2.png`), sometimes the offer as a PDF,
and the CV sent (`CV_<Name>.pdf`, often its `.tex`). Some companies have files at
their own level too: an older application, kept beside the newer ones.

Every directory that directly holds offer or CV files is one application. A few names are not
applications at all (the CV workshop, a Python venv, an empty "New folder"): they are skipped
with a reason, never silently.
"""

from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path


class FileKind(StrEnum):
    OFFER = "offer"  # a screenshot or a PDF of the posting
    CV = "cv"  # the CV sent: PDF, its LaTeX source, or a word-processor file
    LETTER = "letter"  # a cover letter
    OTHER = "other"


_IMAGES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_DOCUMENTS = frozenset({".pdf", ".tex", ".odt", ".doc", ".docx"})
_EVIDENCE = _IMAGES | _DOCUMENTS
# Directories that hold no application: the CV workshop, tooling, scratch.
_NOT_APPLICATIONS = frozenset({"cv", "new folder", "venv", ".venv", "__pycache__", ".git"})


def classify(path: Path, siblings: frozenset[str]) -> FileKind:
    """What one file of an application folder is. `siblings` are the folder's file names."""
    suffix = path.suffix.lower()
    stem = path.stem.lower()
    if suffix in _IMAGES:
        return FileKind.OFFER
    if suffix not in _DOCUMENTS:
        return FileKind.OTHER
    if stem in {"lm", "cover", "cover_letter", "letter"} or stem.startswith(("lm_", "cover")):
        return FileKind.LETTER
    if suffix != ".pdf" or "cv" in stem or f"{path.stem}.tex" in siblings:
        return FileKind.CV
    return FileKind.OFFER  # offer.pdf, 1.pdf: a posting saved as PDF


@dataclass(frozen=True)
class DossierEntry:
    """One application folder, relative to the scanned root."""

    company: str  # the top-level folder name
    role: str | None  # the path below the company folder; None for files at company level
    relative: str  # the folder, relative to the root ("" segments joined by "/")
    files: dict[str, FileKind]  # file name → kind
    first_seen: date | None  # the oldest offer file's timestamp (else the oldest file's)
    # Files of a parent folder that holds a CV but no offer: the CV shared by its sub-folders
    # (`Citadel Securities/CV.pdf` beside `Citadel Securities/MLE/1.png`). Root-relative.
    inherited: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkippedPath:
    relative: str
    reason: str


@dataclass
class DossierScan:
    entries: list[DossierEntry] = field(default_factory=list)
    skipped: list[SkippedPath] = field(default_factory=list)


def _day(path: Path) -> date:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).date()


def _entry(
    root: Path, folder: Path, files: list[Path], company: str, inherited: tuple[str, ...]
) -> DossierEntry:
    names = frozenset(file.name for file in files)
    kinds = {file.name: classify(file, names) for file in files}
    dated = [file for file in files if kinds[file.name] is FileKind.OFFER] or files
    parts = folder.relative_to(root).parts
    return DossierEntry(
        company=company,
        role="/".join(parts[1:]) or None,
        relative="/".join(parts),
        files=dict(sorted(kinds.items())),
        first_seen=min(_day(file) for file in dated) if dated else None,
        inherited=inherited,
    )


def _walk(
    root: Path, folder: Path, company: str, scan: DossierScan, inherited: tuple[str, ...] = ()
) -> None:
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _EVIDENCE)
    children = sorted(
        p for p in folder.iterdir() if p.is_dir() and p.name.lower() not in _NOT_APPLICATIONS
    )
    if files:
        entry = _entry(root, folder, files, company, inherited)
        if children and FileKind.OFFER not in entry.files.values():
            inherited = inherited + tuple(
                f"{entry.relative}/{name}" for name in entry.files
            )  # a CV for the sub-folders, not an application of its own
        else:
            scan.entries.append(entry)
    for child in sorted(p for p in folder.iterdir() if p.is_dir()):
        if child.name.lower() in _NOT_APPLICATIONS:
            scan.skipped.append(SkippedPath(str(child.relative_to(root)), "not an application"))
            continue
        _walk(root, child, company, scan, inherited)


def scan_dossier(root: Path) -> DossierScan:
    """Every application folder under `root` (one level of company folders)."""
    scan = DossierScan()
    loose: list[Path] = []
    for child in sorted(root.iterdir()):
        relative = child.name
        if child.is_dir():
            if child.name.lower() in _NOT_APPLICATIONS:
                scan.skipped.append(SkippedPath(relative, "not an application"))
            elif not any(child.rglob("*")):
                scan.skipped.append(SkippedPath(relative, "empty"))
            else:
                _walk(root, child, child.name, scan)
        elif child.suffix.lower() in _IMAGES:
            # A screenshot left at the root, named after its company ("RJC Group.png"): it
            # belongs to that company's own folder when there is one.
            if (root / child.stem).is_dir():
                loose.append(child)
                continue
            scan.entries.append(
                DossierEntry(
                    company=child.stem,
                    role=None,
                    relative=child.name,
                    files={child.name: FileKind.OFFER},
                    first_seen=_day(child),
                )
            )
        else:
            scan.skipped.append(SkippedPath(relative, "loose file, not tied to a company"))
    for image in loose:
        owners = [i for i, e in enumerate(scan.entries) if e.relative == image.stem]
        if owners:
            owner = scan.entries[owners[0]]
            scan.entries[owners[0]] = replace(owner, inherited=(*owner.inherited, image.name))
        else:
            scan.skipped.append(SkippedPath(image.name, "screenshot beside an empty folder"))
    return scan
