"""The contract every collector honors — blueprint/03-INTERFACES.md §3.1.

Four lines, and that is all a collector implements: it calls, it validates
into `RawPosting`, it hands back a `CollectResult`. It never persists, never
normalizes, never decides cadence — that is `store`, `normalize`, and the
`runtime` scheduler's job respectively.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from jobtracker.collect.http import HttpClient, HttpSession
from jobtracker.core.enums import Source
from jobtracker.core.models import Board, CollectResult, RawPosting


class Collector(Protocol):
    source: Source

    def fetch(self, board: Board, session: HttpSession) -> CollectResult: ...


@dataclass(frozen=True)
class AggregatorSetup:
    """Everything `collect/aggregators/` hands the runtime — the one seam between them.

    Defined here, outside the aggregators package, so `runtime` can name the type
    without importing a directory that must stay deletable
    (blueprint/wp/WP13-aggregators.md §6). An aggregator query is not a company,
    but it has the same shape as a board — a token, some params, a schedule — so
    each configured query is handed over as a pseudo-`Board`.
    """

    collectors: Mapping[Source, Collector]
    boards: list[Board]
    client_factories: Mapping[Source, Callable[[], HttpClient]] = field(default_factory=dict)
    # Maps an aggregator's employer name onto the registry's `company_slug` when
    # they are the same company — the precondition for cross-source dedup (§3.4).
    resolve_employer: Callable[[RawPosting], RawPosting] = lambda raw: raw
