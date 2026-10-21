"""Five months without news: abandoned, with nothing stored — WP21 §2."""

from datetime import date

from jobtracker.career.lifecycle import is_abandoned, is_open, months_after
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus
from jobtracker.core.models import Application, ApplicationEvent

_TODAY = date(2026, 10, 21)


def _application(
    status: ApplicationStatus, applied_on: date | None, *events: ApplicationEvent
) -> Application:
    return Application(
        application_id="a",
        company="Acme",
        company_slug=None,
        title=None,
        location=None,
        applied_on=applied_on,
        applied_on_estimated=False,
        closed_on=None,
        status=status,
        reason="",
        posting_id=None,
        dossier=None,
        origin=ApplicationOrigin.IMPORT,
        events=events,
    )


def test_months_after_clamps_to_the_end_of_month() -> None:
    assert months_after(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert months_after(date(2025, 10, 15), 5) == date(2026, 3, 15)


def test_waiting_more_than_five_months_is_abandoned() -> None:
    old = _application(ApplicationStatus.APPLIED, date(2026, 5, 20))
    recent = _application(ApplicationStatus.APPLIED, date(2026, 5, 21))
    assert is_abandoned(old, _TODAY) and not is_open(old, _TODAY)
    assert not is_abandoned(recent, _TODAY) and is_open(recent, _TODAY)


def test_the_clock_restarts_at_the_latest_news() -> None:
    interviewed = _application(
        ApplicationStatus.INTERVIEW,
        date(2026, 1, 5),
        ApplicationEvent(on_date=date(2026, 1, 5), status=ApplicationStatus.APPLIED),
        ApplicationEvent(on_date=date(2026, 9, 1), status=ApplicationStatus.INTERVIEW),
    )
    assert is_open(interviewed, _TODAY)


def test_a_closed_application_is_neither_open_nor_abandoned() -> None:
    rejected = _application(ApplicationStatus.REJECTED, date(2024, 6, 1))
    assert not is_open(rejected, _TODAY)
    assert not is_abandoned(rejected, _TODAY)


def test_an_undated_application_is_never_called_abandoned() -> None:
    assert not is_abandoned(_application(ApplicationStatus.APPLIED, None), _TODAY)
