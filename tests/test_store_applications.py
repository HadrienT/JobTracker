import sqlite3
from datetime import date

import pytest

from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus
from jobtracker.core.models import Application, ApplicationEvent
from jobtracker.store.applications import get_application, list_applications, upsert_application

pytestmark = pytest.mark.db


def _application(**overrides: object) -> Application:
    base: dict[str, object] = {
        "application_id": "app-1",
        "company": "Acme",
        "company_slug": None,
        "title": "Quant Dev",
        "location": "UK (London)",
        "applied_on": date(2026, 10, 7),
        "applied_on_estimated": False,
        "closed_on": None,
        "status": ApplicationStatus.APPLIED,
        "reason": "Waiting for answer",
        "posting_id": None,
        "dossier": "Acme/Quant Dev",
        "origin": ApplicationOrigin.IMPORT,
        "events": (ApplicationEvent(on_date=date(2026, 10, 7), status=ApplicationStatus.APPLIED),),
    }
    base.update(overrides)
    return Application(**base)  # type: ignore[arg-type]


def test_an_application_round_trips_with_its_history(store_conn: sqlite3.Connection) -> None:
    upsert_application(store_conn, _application())
    assert get_application(store_conn, "app-1") == _application()


def test_a_reimport_keeps_the_note_and_rewrites_the_history(
    store_conn: sqlite3.Connection,
) -> None:
    upsert_application(store_conn, _application())
    store_conn.execute(
        "UPDATE applications SET note = 'called back' WHERE application_id = 'app-1'"
    )
    rejected = (
        ApplicationEvent(on_date=date(2026, 10, 7), status=ApplicationStatus.APPLIED),
        ApplicationEvent(
            on_date=date(2026, 10, 12), status=ApplicationStatus.REJECTED, reason="Not interested"
        ),
    )
    upsert_application(
        store_conn,
        _application(
            status=ApplicationStatus.REJECTED, closed_on=date(2026, 10, 12), events=rejected
        ),
    )
    stored = get_application(store_conn, "app-1")
    assert stored is not None
    assert stored.note == "called back"
    assert stored.status is ApplicationStatus.REJECTED
    assert stored.events == rejected


def test_list_is_newest_first_with_undated_last(store_conn: sqlite3.Connection) -> None:
    upsert_application(store_conn, _application(application_id="old", applied_on=date(2024, 6, 1)))
    upsert_application(store_conn, _application(application_id="undated", applied_on=None))
    upsert_application(store_conn, _application(application_id="new", applied_on=date(2026, 10, 7)))
    assert [a.application_id for a in list_applications(store_conn)] == ["new", "old", "undated"]


def test_the_status_check_rejects_a_typo(store_conn: sqlite3.Connection) -> None:
    upsert_application(store_conn, _application())
    with pytest.raises(sqlite3.IntegrityError):
        store_conn.execute("UPDATE applications SET status = 'ghosted'")
