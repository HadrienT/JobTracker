"""Application tracking over the API — blueprint/wp/WP18-tracking.md."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from factories_store import make_board, make_posting, make_verdict
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting

pytestmark = pytest.mark.db


def _seed(conn: sqlite3.Connection, posting_id: str, *, active: bool = True) -> None:
    posting = make_posting(
        posting_id=posting_id,
        source_job_id=posting_id,
        fingerprint=f"fp-{posting_id}",
        title=f"Quant {posting_id}",
    )
    upsert_posting(conn, posting, make_verdict(posting_id=posting_id))
    if not active:
        conn.execute("UPDATE postings SET is_active = 0 WHERE posting_id = ?", (posting_id,))
    conn.commit()


@pytest.fixture
def seeded(api_conn: sqlite3.Connection) -> None:
    sync_companies(api_conn, [make_board()])
    _seed(api_conn, "p-a")
    _seed(api_conn, "p-b")
    _seed(api_conn, "p-closed", active=False)


def _status(client: TestClient, posting_id: str, status: str | None):
    return client.post(f"/postings/{posting_id}/status", json={"status": status})


def _listed(client: TestClient, query: str = "") -> dict[str, str | None]:
    items = client.get(f"/postings?{query}").json()["items"]
    return {item["posting_id"]: item["application_status"] for item in items}


def test_a_posting_starts_untracked(api_client: TestClient, seeded: None) -> None:
    assert _listed(api_client) == {"p-a": None, "p-b": None}
    detail = api_client.get("/postings/p-a").json()
    assert detail["application_status"] is None
    assert detail["note"] == ""


def test_setting_a_status_shows_up_in_the_list_and_the_detail(
    api_client: TestClient, seeded: None
) -> None:
    assert _status(api_client, "p-a", "applied").status_code == 204

    assert _listed(api_client) == {"p-a": "applied", "p-b": None}
    assert api_client.get("/postings/p-a").json()["application_status"] == "applied"


def test_the_status_moves_along_and_null_stops_tracking(
    api_client: TestClient, seeded: None
) -> None:
    for status in ("applied", "interview", "offer"):
        _status(api_client, "p-a", status)
        assert _listed(api_client)["p-a"] == status
    _status(api_client, "p-a", None)
    assert _listed(api_client)["p-a"] is None


def test_an_unknown_status_is_refused(api_client: TestClient, seeded: None) -> None:
    assert _status(api_client, "p-a", "ghosted").status_code == 422


def test_an_unknown_posting_is_a_404(api_client: TestClient, seeded: None) -> None:
    assert _status(api_client, "nope", "applied").status_code == 404
    assert api_client.post("/postings/nope/note", json={"note": "x"}).status_code == 404


def test_the_status_filter_narrows_the_list(api_client: TestClient, seeded: None) -> None:
    _status(api_client, "p-a", "applied")
    _status(api_client, "p-b", "interview")

    assert set(_listed(api_client, "statuses=applied")) == {"p-a"}
    assert set(_listed(api_client, "statuses=applied&statuses=interview")) == {"p-a", "p-b"}


def test_a_tracked_application_stays_listed_after_its_offer_closes(
    api_client: TestClient, api_conn: sqlite3.Connection, seeded: None
) -> None:
    _status(api_client, "p-closed", "applied")

    assert "p-closed" not in _listed(api_client)  # the plain feed hides closed offers
    assert _listed(api_client, "statuses=applied") == {"p-closed": "applied"}


def test_a_note_is_saved_and_comes_back_in_the_detail_only(
    api_client: TestClient, seeded: None
) -> None:
    assert api_client.post("/postings/p-a/note", json={"note": "call Anna"}).status_code == 204

    assert api_client.get("/postings/p-a").json()["note"] == "call Anna"
    assert "note" not in api_client.get("/postings").json()["items"][0]


def test_an_overlong_note_is_refused(api_client: TestClient, seeded: None) -> None:
    assert api_client.post("/postings/p-a/note", json={"note": "x" * 4001}).status_code == 422
    assert api_client.post("/postings/p-a/note", json={"note": "x" * 4000}).status_code == 204


def test_status_note_and_favorite_do_not_overwrite_each_other(
    api_client: TestClient, seeded: None
) -> None:
    api_client.post("/postings/p-a/favorite", json={"value": True})
    _status(api_client, "p-a", "applied")
    api_client.post("/postings/p-a/note", json={"note": "keep me"})
    api_client.post("/postings/p-a/hide", json={"value": False})

    detail = api_client.get("/postings/p-a").json()
    assert (detail["favorited"], detail["application_status"], detail["note"]) == (
        True,
        "applied",
        "keep me",
    )
