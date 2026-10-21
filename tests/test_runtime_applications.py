"""`jobtracker import-applications` end to end, on a fictional history — WP21 §3."""

import sqlite3
from pathlib import Path

import pytest

from factories_store import make_board
from jobtracker.career.dossier import scan_dossier
from jobtracker.career.sheet import parse_sheet
from jobtracker.runtime.applications import ImportOutcome, import_history
from jobtracker.store.applications import list_applications

pytestmark = pytest.mark.db

_SHEET = """\
Country,Company,Job,Application date,Rejection date,Reason
UK (London),Acme,Quant Dev,07/10/2026,12/10/2026,Not interested
CH (Zurich),Borealis,SWE,08/10/2026,,Waiting for answer
"""


def _import(conn: sqlite3.Connection, tmp_path: Path, *, apply: bool) -> ImportOutcome:
    root = tmp_path / "history"
    return import_history(
        conn,
        sheet=parse_sheet(_SHEET),
        dossier=scan_dossier(root),
        dossier_root=root,
        aliases_config={},
        boards=[make_board(company_slug="acme", company_name="Acme")],
        career_root=tmp_path / "career",
        apply=apply,
    )


@pytest.fixture
def history(tmp_path: Path) -> Path:
    folder = tmp_path / "history" / "Acme" / "Quant Dev London"
    folder.mkdir(parents=True)
    (folder / "1.png").write_bytes(b"png")
    (folder / "CV.pdf").write_bytes(b"pdf")
    return tmp_path


def test_a_dry_run_writes_nothing(store_conn: sqlite3.Connection, history: Path) -> None:
    outcome = _import(store_conn, history, apply=False)
    assert len(outcome.reconciliation.applications) == 2
    assert list_applications(store_conn) == []
    assert not (history / "career").exists()


def test_apply_copies_the_files_and_links_the_registry(
    store_conn: sqlite3.Connection, history: Path
) -> None:
    _import(store_conn, history, apply=True)
    applications = {a.company: a for a in list_applications(store_conn)}
    assert applications["Acme"].dossier == "Acme/Quant Dev London"
    assert applications["Acme"].company_slug == "acme"
    copied = history / "career" / "applications" / "Acme" / "Quant Dev London"
    assert sorted(p.name for p in copied.iterdir()) == ["1.png", "CV.pdf"]


def test_apply_twice_changes_nothing(store_conn: sqlite3.Connection, history: Path) -> None:
    _import(store_conn, history, apply=True)
    second = _import(store_conn, history, apply=True)
    assert (second.files_copied, second.purged) == (0, 0)
    assert len(list_applications(store_conn)) == 2


def test_a_row_gone_from_the_history_is_purged_unless_annotated(
    store_conn: sqlite3.Connection, history: Path
) -> None:
    _import(store_conn, history, apply=True)
    store_conn.execute(
        "INSERT INTO applications (application_id, company, status, origin, note, "
        "created_at, updated_at) VALUES "
        "('gone', 'Old Co', 'applied', 'import', '', 'x', 'x'), "
        "('noted', 'Old Co', 'applied', 'import', 'keep me', 'x', 'x'), "
        "('mine', 'New Co', 'applied', 'cli', '', 'x', 'x')"
    )
    outcome = _import(store_conn, history, apply=True)
    assert (outcome.purged, outcome.kept_stale) == (1, 1)
    remaining = {a.application_id for a in list_applications(store_conn)}
    assert {"noted", "mine"} <= remaining
    assert "gone" not in remaining
