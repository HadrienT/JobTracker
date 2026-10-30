"""The CV registry — blueprint/wp/WP22-cvs.md."""

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from factories_store import make_board, make_posting, make_verdict
from jobtracker.career.cvs import cv_id_of, cv_path, save_cv
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus, CvSource
from jobtracker.core.models import Application, ApplicationEvent
from jobtracker.runtime.cv_backfill import apply_backfill, plan_backfill
from jobtracker.store.applications import (
    create_application,
    get_application,
    import_application,
    set_application_cv,
)
from jobtracker.store.companies import sync_companies
from jobtracker.store.cvs import add_cv, current_cv_id, list_cvs
from jobtracker.store.postings import upsert_posting

pytestmark = pytest.mark.db

V1 = b"%PDF-1.5 first version"
V2 = b"%PDF-1.5 second version"
TAILORED = b"%PDF-1.5 written for one offer"


def _application(
    application_id: str, dossier: str | None = None, on: date = date(2026, 10, 7)
) -> Application:
    return Application(
        application_id=application_id,
        company="Acme",
        company_slug=None,
        title="Quant Dev",
        location="UK (London)",
        applied_on=on,
        applied_on_estimated=False,
        closed_on=None,
        status=ApplicationStatus.APPLIED,
        reason="",
        posting_id=None,
        dossier=dossier,
        origin=ApplicationOrigin.IMPORT,
        events=(ApplicationEvent(on_date=on, status=ApplicationStatus.APPLIED),),
    )


def _folder(career: Path, dossier: str, **files: bytes) -> None:
    folder = career / "applications" / dossier
    folder.mkdir(parents=True)
    for name, data in files.items():
        (folder / name.replace("__", ".")).write_bytes(data)


def _add(conn: sqlite3.Connection, data: bytes, *, pinned: bool, day: str = "2026-01-01") -> str:
    cv_id = cv_id_of(data)
    add_cv(
        conn,
        cv_id,
        label="cv",
        file_name="cv.pdf",
        size=len(data),
        pinned=pinned,
        created_at=datetime.fromisoformat(f"{day}T00:00:00+00:00"),
    )
    return cv_id


def test_identical_bytes_are_one_file(tmp_path: Path) -> None:
    assert save_cv(tmp_path, V1) == save_cv(tmp_path, V1) == cv_id_of(V1)
    assert save_cv(tmp_path, V2) != cv_id_of(V1)
    assert sorted(p.read_bytes() for p in (tmp_path / "cvs").iterdir()) == sorted([V1, V2])
    assert cv_path(tmp_path, cv_id_of(V1)).read_bytes() == V1


def test_the_same_cv_under_two_names_is_one_entry_and_keeps_its_label(
    api_conn: sqlite3.Connection,
) -> None:
    cv_id = _add(api_conn, V1, pinned=False)
    add_cv(
        api_conn,
        cv_id,
        label="other",
        file_name="other.pdf",
        size=1,
        pinned=True,
        created_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    ((only),) = list_cvs(api_conn)
    assert (only.label, only.file_name, only.pinned) == ("cv", "cv.pdf", True)


def test_the_backfill_links_by_content_whatever_the_file_is_called(
    api_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    career = tmp_path / "career"
    _folder(career, "a", CV_Name__pdf=V1, offer__pdf=b"%PDF offer", n1__png=b"x")
    _folder(career, "b", CV_Name_old__pdf=V1)
    _folder(career, "c", CV_Name__pdf=TAILORED)
    for name in "abc":
        create_application(api_conn, _application(name, name))
    plan = plan_backfill(api_conn, career, inferred_names={"CV_Name_old.pdf"})
    assert apply_backfill(api_conn, career, plan) == 2

    by_cv = {cv.cv_id: cv for cv in list_cvs(api_conn)}
    version, tailored = by_cv[cv_id_of(V1)], by_cv[cv_id_of(TAILORED)]
    assert (version.pinned, version.applications, version.label) == (True, 2, "CV_Name")
    assert (tailored.pinned, tailored.applications) == (False, 1)
    assert tailored.label == "Acme — Quant Dev"  # sent once: named after its offer
    assert version.created_at.date() == date(2026, 10, 7)  # first sent, not backfilled

    sources = {n: get_application(api_conn, n) for n in "abc"}
    assert sources["a"].cv_source is CvSource.CONFIRMED  # type: ignore[union-attr]
    assert sources["b"].cv_source is CvSource.INFERRED  # type: ignore[union-attr]
    assert cv_path(career, version.cv_id).read_bytes() == V1
    assert (career / "applications" / "b" / "CV_Name_old.pdf").exists()  # copies stay


def test_the_backfill_guesses_nothing_and_never_overwrites(
    api_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    career = tmp_path / "career"
    _folder(career, "two", CV_a__pdf=V1, CV_b__pdf=V2)
    _folder(career, "broken", CV__pdf=b"not a pdf")
    _folder(career, "none", n1__png=b"x")
    _folder(career, "chosen", CV__pdf=V1)
    for name in ("two", "broken", "none", "chosen"):
        create_application(api_conn, _application(name, name))
    set_application_cv(api_conn, "chosen", _add(api_conn, V2, pinned=True))

    plan = plan_backfill(api_conn, career)
    assert plan.links == []
    assert set(plan.ambiguous) == {"two"}
    assert set(plan.unreadable) == {"broken"}
    assert set(plan.without_cv) == {"broken", "none"}


def test_a_folder_own_cv_wins_over_the_one_of_its_parent(
    api_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    career = tmp_path / "career"
    _folder(career, "Acme/Old", n1__png=b"x")
    _folder(career, "Acme/New", n1__png=b"x", CV__pdf=V2)
    (career / "applications" / "Acme" / "CV.pdf").write_bytes(V1)
    create_application(api_conn, _application("old", "Acme/Old"))
    create_application(api_conn, _application("new", "Acme/New"))
    links = {
        link.application.application_id: link for link in plan_backfill(api_conn, career).links
    }
    assert links["old"].cv_id == cv_id_of(V1)  # shared from above
    assert links["new"].cv_id == cv_id_of(V2)


def test_the_backfill_is_no_hand_edit_for_the_import(
    api_conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """A linked row stays the import's to refresh, and a refresh keeps the link."""
    career = tmp_path / "career"
    _folder(career, "a", CV__pdf=V1)
    import_application(api_conn, _application("a", "a"))
    apply_backfill(api_conn, career, plan_backfill(api_conn, career))
    refreshed = _application("a", "a").model_copy(update={"title": "New title"})
    assert import_application(api_conn, refreshed) is True
    found = get_application(api_conn, "a")
    assert found is not None
    assert (found.title, found.cv_id) == ("New title", cv_id_of(V1))


def test_a_hand_choice_survives_the_import(api_conn: sqlite3.Connection) -> None:
    import_application(api_conn, _application("a"))
    set_application_cv(api_conn, "a", _add(api_conn, V1, pinned=True))
    assert import_application(api_conn, _application("a")) is False


def test_current_is_the_last_version_sent_or_added_never_a_tailored_cv(
    api_conn: sqlite3.Connection,
) -> None:
    assert current_cv_id(api_conn) is None
    v1 = _add(api_conn, V1, pinned=True)
    v2 = _add(api_conn, V2, pinned=True)
    tailored = _add(api_conn, TAILORED, pinned=False)
    create_application(api_conn, _application("old", on=date(2026, 3, 1)))
    create_application(api_conn, _application("new", on=date(2026, 10, 1)))
    create_application(api_conn, _application("last", on=date(2026, 10, 30)))
    set_application_cv(api_conn, "old", v2)
    set_application_cv(api_conn, "new", v1)
    set_application_cv(api_conn, "last", tailored)
    assert current_cv_id(api_conn) == v1
    v3 = _add(api_conn, b"%PDF-1.5 third", pinned=True, day="2026-10-31")
    assert current_cv_id(api_conn) == v3  # just added, not sent yet


def test_a_cv_is_uploaded_once_and_served(api_client: TestClient) -> None:
    first = api_client.post("/cvs?name=My CV.pdf", content=V1)
    assert first.status_code == 201
    body = first.json()
    assert (body["label"], body["pinned"], body["current"]) == ("My CV", True, True)
    assert api_client.post("/cvs?name=again.pdf", content=V1).json()["cv_id"] == body["cv_id"]
    assert len(api_client.get("/cvs").json()) == 1

    served = api_client.get(f"/cvs/{body['cv_id']}/file")
    assert (served.status_code, served.content) == (200, V1)
    assert served.headers["content-type"] == "application/pdf"
    assert served.headers["content-disposition"].startswith("inline")

    renamed = api_client.post(f"/cvs/{body['cv_id']}/edit", json={"label": "v1"}).json()
    assert renamed["label"] == "v1"


def test_only_a_pdf_gets_in(api_client: TestClient) -> None:
    assert api_client.post("/cvs?name=cv.pdf", content=b"<html>").status_code == 422
    assert api_client.post("/cvs?name=cv.pdf", content=b"").status_code == 422
    assert api_client.get("/cvs/../../etc/passwd/file").status_code == 404
    assert api_client.get("/cvs/nope/file").status_code == 404


def test_choosing_confirming_and_clearing_the_cv(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    create_application(api_conn, _application("a"))
    api_conn.commit()
    cv_id = api_client.post("/cvs?name=cv.pdf", content=V1).json()["cv_id"]
    set_application_cv(api_conn, "a", cv_id, CvSource.INFERRED)
    api_conn.commit()
    assert api_client.get("/applications").json()[0]["cv_source"] == "inferred"

    confirmed = api_client.post("/applications/a/cv", json={"cv_id": cv_id}).json()
    assert (confirmed["cv_id"], confirmed["cv_source"]) == (cv_id, "confirmed")
    assert api_client.get("/cvs").json()[0]["applications"] == 1

    cleared = api_client.post("/applications/a/cv", json={"cv_id": None}).json()
    assert (cleared["cv_id"], cleared["cv_source"]) == (None, None)
    assert api_client.post("/applications/a/cv", json={"cv_id": "nope"}).status_code == 422


def test_a_new_application_assumes_the_current_version_unless_told(
    api_client: TestClient,
) -> None:
    cv_id = api_client.post("/cvs?name=cv.pdf", content=V1).json()["cv_id"]
    fields = {"company": "Acme", "title": "Quant"}
    assumed = api_client.post("/applications", json=fields).json()
    assert (assumed["cv_id"], assumed["cv_source"]) == (cv_id, "inferred")
    chosen = api_client.post("/applications", json={**fields, "cv_id": cv_id}).json()
    assert (chosen["cv_id"], chosen["cv_source"]) == (cv_id, "confirmed")
    none = api_client.post("/applications", json={**fields, "cv_id": None}).json()
    assert (none["cv_id"], none["cv_source"]) == (None, None)


def test_marking_a_posting_applied_assumes_the_current_version(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    sync_companies(api_conn, [make_board()])
    upsert_posting(api_conn, make_posting(posting_id="p-1"), make_verdict(posting_id="p-1"))
    api_conn.commit()
    cv_id = api_client.post("/cvs?name=cv.pdf", content=V1).json()["cv_id"]
    response = api_client.post("/postings/p-1/status", json={"status": "applied"})
    assert response.status_code < 300
    created = api_client.get("/applications").json()[0]
    assert (created["cv_id"], created["cv_source"]) == (cv_id, "inferred")


def test_a_cv_attached_as_a_file_is_the_one_sent(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    current = api_client.post("/cvs?name=cv.pdf", content=V1).json()["cv_id"]
    created = api_client.post("/applications", json={"company": "Acme", "title": "Quant"}).json()
    application_id = created["application_id"]
    assert created["cv_source"] == "inferred"

    api_client.post(f"/applications/{application_id}/files?name=shot.png", content=b"x")
    assert api_client.get(f"/applications/{application_id}").json()["cv_id"] == current

    api_client.post(f"/applications/{application_id}/files?name=CV_Acme.pdf", content=TAILORED)
    attached = api_client.get(f"/applications/{application_id}").json()
    assert (attached["cv_id"], attached["cv_source"]) == (cv_id_of(TAILORED), "confirmed")
    tailored = next(c for c in api_client.get("/cvs").json() if c["cv_id"] == attached["cv_id"])
    assert (tailored["pinned"], tailored["label"]) == (False, "Acme — Quant")

    api_client.post(f"/applications/{application_id}/files?name=CV_later.pdf", content=V2)
    kept = api_client.get(f"/applications/{application_id}").json()
    assert kept["cv_id"] == cv_id_of(TAILORED)  # the user's answer stands
