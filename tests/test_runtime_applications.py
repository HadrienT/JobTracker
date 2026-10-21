"""`jobtracker import-applications` end to end, on a fictional history — WP21 §3."""

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.career.dossier import scan_dossier
from jobtracker.career.sheet import parse_sheet
from jobtracker.core.clock import freeze
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus, RemoteMode
from jobtracker.core.models import Location
from jobtracker.runtime.applications import ImportOutcome, adopt_feed_statuses, import_history
from jobtracker.store.applications import (
    import_application,
    list_applications,
    update_application,
)
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import set_application_status, upsert_posting

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


def test_a_row_gone_from_the_history_is_purged_unless_edited(
    store_conn: sqlite3.Connection, history: Path
) -> None:
    _import(store_conn, history, apply=True)
    stale = list_applications(store_conn)[0].model_copy(update={"title": "Gone"})
    for application_id in ("gone", "edited"):
        import_application(store_conn, stale.model_copy(update={"application_id": application_id}))
    update_application(store_conn, "edited", note="keep me")
    outcome = _import(store_conn, history, apply=True)
    assert (outcome.purged, outcome.kept_stale) == (1, 1)
    remaining = {a.application_id for a in list_applications(store_conn)}
    assert "edited" in remaining
    assert "gone" not in remaining


# --- statuses set in the feed before WP21 --------------------------------------------------


def _feed_posting(conn: sqlite3.Connection, posting_id: str, title: str, city: str) -> None:
    posting = make_posting(
        posting_id=posting_id,
        source_job_id=posting_id,
        fingerprint=posting_id,
        title=title,
        title_raw=title,
        locations=(
            Location(city=city, country="GB", region=None, remote_mode=RemoteMode.ONSITE, raw=None),
        ),
    )
    upsert_posting(conn, posting, make_verdict(posting_id=posting_id))


def test_feed_statuses_are_adopted_linked_created_or_triaged(
    store_conn: sqlite3.Connection, history: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("jobtracker.career.offer.html_to_pdf", lambda _html: b"%PDF stub")
    sync_companies(store_conn, [make_board(company_slug="acme", company_name="Acme")])
    _import(store_conn, history, apply=True)  # Acme, Quant Dev, London, 07/10/2026
    _feed_posting(store_conn, "p-recorded", "Quantitative Developer", "London")
    _feed_posting(store_conn, "p-new", "Software Engineer", "Leeds")
    _feed_posting(store_conn, "p-no", "Graduate Trader", "Leeds")
    with freeze(datetime(2026, 10, 7, 12, tzinfo=UTC)):
        set_application_status(store_conn, "p-recorded", ApplicationStatus.APPLIED)
        set_application_status(store_conn, "p-new", ApplicationStatus.APPLIED)
        set_application_status(store_conn, "p-no", ApplicationStatus.WITHDRAWN)

    dry = adopt_feed_statuses(
        store_conn, career_root=history / "career", aliases_config={}, apply=False, render=False
    )
    assert [p for p, _ in dry.linked] == ["p-recorded"]
    assert (dry.created, dry.triaged) == (["p-new"], ["p-no"])
    assert all(a.posting_id is None for a in list_applications(store_conn))

    adopt_feed_statuses(
        store_conn, career_root=history / "career", aliases_config={}, apply=True, render=True
    )
    by_posting = {a.posting_id: a for a in list_applications(store_conn) if a.posting_id}
    assert by_posting["p-recorded"].origin is ApplicationOrigin.IMPORT
    # the sheet knew more than the feed: the posting now shows the rejection
    assert by_posting["p-recorded"].status is ApplicationStatus.REJECTED
    created = by_posting["p-new"]
    assert created.origin is ApplicationOrigin.FEED
    assert created.applied_on == date(2026, 10, 7)
    assert created.dossier is not None
    assert (history / "career" / "applications" / created.dossier / "offer.pdf").is_file()
    flags = dict(
        store_conn.execute(
            "SELECT posting_id, COALESCE(application_status, triage) FROM user_flags"
        ).fetchall()
    )
    assert flags == {"p-recorded": "rejected", "p-new": "applied", "p-no": "no"}

    again = adopt_feed_statuses(
        store_conn, career_root=history / "career", aliases_config={}, apply=True, render=True
    )
    assert (again.linked, again.created, again.triaged) == ([], [], [])
