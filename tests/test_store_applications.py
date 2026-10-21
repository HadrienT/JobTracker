"""Applications in the store, and the feed flag they mirror — WP21 §2."""

import sqlite3
from datetime import date

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus
from jobtracker.core.models import Application, ApplicationEvent
from jobtracker.store.applications import (
    application_for_posting,
    create_application,
    delete_application,
    dossier_name,
    get_application,
    import_application,
    link_posting,
    list_applications,
    match_application_ids,
    purge_stale_imports,
    record_status,
    update_application,
)
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting

pytestmark = pytest.mark.db

_APPLIED = (ApplicationEvent(on_date=date(2026, 10, 7), status=ApplicationStatus.APPLIED),)


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
        "events": _APPLIED,
    }
    base.update(overrides)
    return Application(**base)  # type: ignore[arg-type]


def _posting(conn: sqlite3.Connection, posting_id: str) -> None:
    sync_companies(conn, [make_board()])
    posting = make_posting(posting_id=posting_id, source_job_id=posting_id, fingerprint=posting_id)
    upsert_posting(conn, posting, make_verdict(posting_id=posting_id))


def _flag(conn: sqlite3.Connection, posting_id: str) -> str | None:
    row = conn.execute(
        "SELECT application_status FROM user_flags WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    return row[0] if row is not None else None


def test_an_application_round_trips_with_its_history(store_conn: sqlite3.Connection) -> None:
    create_application(store_conn, _application())
    assert get_application(store_conn, "app-1") == _application()


def test_a_status_grows_the_history_and_closes_on_rejection(
    store_conn: sqlite3.Connection,
) -> None:
    create_application(store_conn, _application())
    record_status(store_conn, "app-1", ApplicationStatus.INTERVIEW, on_date=date(2026, 10, 12))
    record_status(
        store_conn,
        "app-1",
        ApplicationStatus.REJECTED,
        on_date=date(2026, 10, 20),
        reason="Failed 2nd interview",
    )
    stored = get_application(store_conn, "app-1")
    assert stored is not None
    assert [e.status for e in stored.events] == [
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
    ]
    assert stored.closed_on == date(2026, 10, 20)
    assert stored.reason == "Failed 2nd interview"


def test_the_feed_flag_mirrors_the_linked_application(store_conn: sqlite3.Connection) -> None:
    _posting(store_conn, "p-1")
    _posting(store_conn, "p-2")
    create_application(store_conn, _application(posting_id="p-1"))
    assert _flag(store_conn, "p-1") == "applied"

    record_status(store_conn, "app-1", ApplicationStatus.INTERVIEW, on_date=None)
    assert _flag(store_conn, "p-1") == "interview"

    link_posting(store_conn, "app-1", "p-2")  # moved: the old posting is untracked
    assert (_flag(store_conn, "p-1"), _flag(store_conn, "p-2")) == (None, "interview")

    delete_application(store_conn, "app-1")
    assert _flag(store_conn, "p-2") is None


def test_an_untracked_posting_gets_no_empty_flags_row(store_conn: sqlite3.Connection) -> None:
    # An empty user_flags row would exempt the posting from the retention purge.
    _posting(store_conn, "p-1")
    create_application(store_conn, _application())
    link_posting(store_conn, "app-1", None)
    assert store_conn.execute("SELECT COUNT(*) FROM user_flags").fetchone()[0] == 0


def test_a_reimport_refreshes_an_untouched_row_and_spares_an_edited_one(
    store_conn: sqlite3.Connection,
) -> None:
    import_application(store_conn, _application(application_id="untouched"))
    import_application(store_conn, _application(application_id="edited"))
    update_application(store_conn, "edited", note="called back")

    rejected = _application(status=ApplicationStatus.REJECTED, reason="Not interested")
    assert import_application(
        store_conn, rejected.model_copy(update={"application_id": "untouched"})
    )
    assert not import_application(
        store_conn, rejected.model_copy(update={"application_id": "edited"})
    )

    statuses = {a.application_id: a.status for a in list_applications(store_conn)}
    assert statuses == {
        "untouched": ApplicationStatus.REJECTED,
        "edited": ApplicationStatus.APPLIED,
    }


def test_stale_imports_are_purged_unless_edited(store_conn: sqlite3.Connection) -> None:
    for application_id in ("kept", "gone", "edited"):
        import_application(store_conn, _application(application_id=application_id))
    record_status(store_conn, "edited", ApplicationStatus.INTERVIEW, on_date=None)
    create_application(
        store_conn, _application(application_id="mine", origin=ApplicationOrigin.CLI)
    )
    assert purge_stale_imports(store_conn, keep={"kept"}) == (1, 1)
    assert {a.application_id for a in list_applications(store_conn)} == {"kept", "edited", "mine"}


def test_application_for_posting_and_id_prefixes(store_conn: sqlite3.Connection) -> None:
    _posting(store_conn, "p-1")
    create_application(store_conn, _application(application_id="01ABC", posting_id="p-1"))
    create_application(store_conn, _application(application_id="01ABD"))
    found = application_for_posting(store_conn, "p-1")
    assert found is not None
    assert found.application_id == "01ABC"
    assert match_application_ids(store_conn, "01AB") == ["01ABC", "01ABD"]
    assert match_application_ids(store_conn, "01ABC") == ["01ABC"]
    assert match_application_ids(store_conn, "%") == []


def test_list_is_newest_first_with_undated_last(store_conn: sqlite3.Connection) -> None:
    create_application(store_conn, _application(application_id="old", applied_on=date(2024, 6, 1)))
    create_application(store_conn, _application(application_id="undated", applied_on=None))
    create_application(store_conn, _application(application_id="new", applied_on=date(2026, 10, 7)))
    assert [a.application_id for a in list_applications(store_conn)] == ["new", "old", "undated"]


def test_the_status_check_rejects_a_typo(store_conn: sqlite3.Connection) -> None:
    create_application(store_conn, _application())
    with pytest.raises(sqlite3.IntegrityError):
        store_conn.execute("UPDATE applications SET status = 'ghosted'")


def test_dossier_names_are_dated_slugs() -> None:
    assert dossier_name(date(2026, 10, 21), "Société Générale", "Quant Dev (NY) / C++") == (
        "2026-10-21-societe-generale-quant-dev-ny-c"
    )
