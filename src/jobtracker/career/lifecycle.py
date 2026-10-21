"""When an application is still worth waiting on — blueprint/wp/WP21-applications.md §2.

An application still `applied` or `interview` with no news for five months is treated as
abandoned: it no longer counts as open. Nothing is stored for it — no status, no flag — so the
day news comes and a status is recorded, it is open or closed by that status alone.
"""

import calendar
from datetime import date

from jobtracker.core.enums import ApplicationStatus
from jobtracker.core.models import Application

ABANDONED_AFTER_MONTHS = 5
_WAITING = frozenset({ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW})


def months_after(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def last_news(application: Application) -> date | None:
    """The latest dated step of the history, else the application date."""
    dated = [event.on_date for event in application.events if event.on_date is not None]
    return max(dated, default=application.applied_on)


def is_abandoned(application: Application, today: date) -> bool:
    if application.status not in _WAITING:
        return False
    news = last_news(application)
    return news is not None and months_after(news, ABANDONED_AFTER_MONTHS) < today


def is_open(application: Application, today: date) -> bool:
    """Still waiting on an answer, and not for so long that it has been given up on."""
    return application.status in _WAITING and not is_abandoned(application, today)
