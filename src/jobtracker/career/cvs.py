"""CVs, one file per content — blueprint/wp/WP22-cvs.md.

The registry's files: `<career_root>/cvs/<sha256>.pdf`. Identical bytes are one CV, whatever the
file was called; a CV is never overwritten, since a different content is a different id.
"""

import hashlib
from pathlib import Path

_PDF_MAGIC = b"%PDF-"


def cv_id_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_pdf(data: bytes) -> bool:
    return data.startswith(_PDF_MAGIC)


def cv_path(career_root: Path, cv_id: str) -> Path:
    return career_root / "cvs" / f"{cv_id}.pdf"


def save_cv(career_root: Path, data: bytes) -> str:
    """Store the file unless its content is already there; returns its id."""
    cv_id = cv_id_of(data)
    target = cv_path(career_root, cv_id)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(".part")
        partial.write_bytes(data)
        partial.replace(target)
    return cv_id
