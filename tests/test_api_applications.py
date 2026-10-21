"""`/applications` — the Applications tab's API (blueprint/wp/WP21-applications.md §6)."""

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import STUB_PDF
from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus
from jobtracker.core.models import Application, ApplicationEvent
from jobtracker.store.applications import create_application
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting

pytestmark = pytest.mark.db


def _imported(
    conn: sqlite3.Connection, application_id: str, applied_on: date, dossier: str | None = None
) -> None:
    create_application(
        conn,
        Application(
            application_id=application_id,
            company="Acme",
            company_slug=None,
            title="Quant Dev",
            location="UK (London)",
            applied_on=applied_on,
            applied_on_estimated=False,
            closed_on=None,
            status=ApplicationStatus.APPLIED,
            reason="Waiting for answer",
            posting_id=None,
            dossier=dossier,
            origin=ApplicationOrigin.IMPORT,
            events=(ApplicationEvent(on_date=applied_on, status=ApplicationStatus.APPLIED),),
        ),
    )
    conn.commit()


def _career(tmp_path: Path) -> Path:
    return tmp_path / "career" / "applications"


def test_the_list_derives_open_and_abandoned_without_storing_them(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    today = utc_now().date()
    _imported(api_conn, "recent", today - timedelta(days=10))
    _imported(api_conn, "old", today - timedelta(days=200))
    listed = {a["application_id"]: a for a in api_client.get("/applications").json()}
    assert (listed["recent"]["open"], listed["recent"]["abandoned"]) == (True, False)
    assert (listed["old"]["open"], listed["old"]["abandoned"]) == (False, True)
    assert listed["old"]["status"] == "applied"  # nothing was rewritten


def test_typing_in_an_application_archives_the_pasted_offer(
    api_client: TestClient, tmp_path: Path
) -> None:
    response = api_client.post(
        "/applications",
        json={
            "company": "Fictive Capital",
            "title": "Junior Quant Developer",
            "location": "Zurich",
            "offer_text": "We build pricing libraries.\n\n- C++20",
            "note": "referral",
        },
    )
    assert response.status_code == 201
    created = response.json()
    assert (created["origin"], created["status"], created["note"]) == ("cli", "applied", "referral")
    detail = api_client.get(f"/applications/{created['application_id']}").json()
    assert [f["name"] for f in detail["files"]] == ["offer.pdf"]
    assert (_career(tmp_path) / detail["dossier"] / "offer.pdf").read_bytes() == STUB_PDF


def test_a_known_url_links_the_collected_posting(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    sync_companies(api_conn, [make_board()])
    posting = make_posting(posting_id="p-1", url="https://example.com/jobs/1")
    upsert_posting(api_conn, posting, make_verdict(posting_id="p-1"))
    api_conn.commit()
    created = api_client.post(
        "/applications",
        json={"company": "Acme", "title": "Quant", "url": "https://example.com/jobs/1"},
    ).json()
    assert created["posting_id"] == "p-1"
    assert api_client.get("/postings/p-1").json()["application_status"] == "applied"


def test_status_edit_and_delete(api_client: TestClient, api_conn: sqlite3.Connection) -> None:
    _imported(api_conn, "a-1", date(2026, 10, 7))
    moved = api_client.post(
        "/applications/a-1/status",
        json={"status": "rejected", "on_date": "2026-10-12", "reason": "Job filled"},
    ).json()
    assert (moved["status"], moved["closed_on"], moved["reason"]) == (
        "rejected",
        "2026-10-12",
        "Job filled",
    )
    assert [e["status"] for e in moved["events"]] == ["applied", "rejected"]

    edited = api_client.post(
        "/applications/a-1/edit", json={"title": "Quant Developer", "note": "follow up"}
    ).json()
    assert (edited["title"], edited["note"], edited["company"]) == (
        "Quant Developer",
        "follow up",
        "Acme",
    )

    assert api_client.post("/applications/a-1/delete").status_code == 204
    assert api_client.get("/applications/a-1").status_code == 404


def test_files_are_attached_listed_and_served_only_from_their_folder(
    api_client: TestClient, api_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    folder = _career(tmp_path) / "Acme" / "Quant Dev London"
    folder.mkdir(parents=True)
    (folder / "1.png").write_bytes(b"png")
    (folder.parent / "CV_Shared.pdf").write_bytes(b"cv")  # a CV kept above the job folders
    (_career(tmp_path) / "Other").mkdir()
    (_career(tmp_path) / "Other" / "secret.pdf").write_bytes(b"no")
    _imported(api_conn, "a-1", date(2026, 10, 7), dossier="Acme/Quant Dev London")

    uploaded = api_client.post(
        "/applications/a-1/files?name=../../CV final.pdf",
        content=b"%PDF cv",
        headers={"content-type": "application/octet-stream"},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["name"] == "CV final.pdf"  # the path part is dropped

    files = {f["name"]: f for f in api_client.get("/applications/a-1").json()["files"]}
    assert set(files) == {"1.png", "CV final.pdf", "CV_Shared.pdf"}
    assert (files["1.png"]["kind"], files["CV_Shared.pdf"]["kind"]) == ("offer", "cv")

    served = api_client.get(f"/applications/a-1/files/{files['CV final.pdf']['path']}")
    assert served.status_code == 200
    assert served.content == b"%PDF cv"
    assert api_client.get("/applications/a-1/files/Other/secret.pdf").status_code == 404
    assert api_client.get("/applications/a-1/files/../jobtracker.db").status_code == 404


def test_an_offer_needs_text_or_a_posting(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    _imported(api_conn, "a-1", date(2026, 10, 7))
    assert api_client.post("/applications/a-1/offer", json={}).status_code == 422
    archived = api_client.post("/applications/a-1/offer", json={"text": "The offer."}).json()
    assert [f["name"] for f in archived["files"]] == ["offer.pdf"]
    assert archived["dossier"] is not None  # a folder was made for it
