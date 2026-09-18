"""`Collector` conformance — blueprint/wp/WP04-collect-core.md §7.

Assigning each concrete collector to a `Collector`-typed variable is a static
check: `mypy --strict` fails this file if any of the three ever drifts from
the four-line protocol (blueprint/03-INTERFACES.md §3.1).
"""

from jobtracker.collect.ats.ashby import AshbyCollector
from jobtracker.collect.ats.greenhouse import GreenhouseCollector
from jobtracker.collect.ats.lever import LeverCollector
from jobtracker.collect.base import Collector
from jobtracker.core.enums import Source

_greenhouse: Collector = GreenhouseCollector()
_lever: Collector = LeverCollector()
_ashby: Collector = AshbyCollector()


def test_each_collector_exposes_its_own_source() -> None:
    assert _greenhouse.source == Source.GREENHOUSE
    assert _lever.source == Source.LEVER
    assert _ashby.source == Source.ASHBY
