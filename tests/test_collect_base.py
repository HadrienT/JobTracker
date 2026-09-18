"""`Collector` conformance — blueprint/wp/WP04-collect-core.md §7.

Assigning each concrete collector to a `Collector`-typed variable is a static
check: `mypy --strict` fails this file if any of them ever drifts from the
four-line protocol (blueprint/03-INTERFACES.md §3.1).
"""

from jobtracker.collect import custom
from jobtracker.collect.ats.ashby import AshbyCollector
from jobtracker.collect.ats.greenhouse import GreenhouseCollector
from jobtracker.collect.ats.lever import LeverCollector
from jobtracker.collect.ats.personio import PersonioCollector
from jobtracker.collect.ats.recruitee import RecruiteeCollector
from jobtracker.collect.ats.smartrecruiters import SmartRecruitersCollector
from jobtracker.collect.ats.workable import WorkableCollector
from jobtracker.collect.ats.workday import WorkdayCollector
from jobtracker.collect.base import Collector
from jobtracker.core.enums import Source

_greenhouse: Collector = GreenhouseCollector()
_lever: Collector = LeverCollector()
_ashby: Collector = AshbyCollector()
_workday: Collector = WorkdayCollector()
_smartrecruiters: Collector = SmartRecruitersCollector()
_workable: Collector = WorkableCollector()
_recruitee: Collector = RecruiteeCollector()
_personio: Collector = PersonioCollector()
_custom: Collector = custom.CustomCollector()


def test_each_collector_exposes_its_own_source() -> None:
    assert _greenhouse.source == Source.GREENHOUSE
    assert _lever.source == Source.LEVER
    assert _ashby.source == Source.ASHBY
    assert _workday.source == Source.WORKDAY
    assert _smartrecruiters.source == Source.SMARTRECRUITERS
    assert _workable.source == Source.WORKABLE
    assert _recruitee.source == Source.RECRUITEE
    assert _personio.source == Source.PERSONIO
    assert _custom.source == Source.CUSTOM
