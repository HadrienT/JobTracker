"""The contract every collector honors — blueprint/03-INTERFACES.md §3.1.

Four lines, and that is all a collector implements: it calls, it validates
into `RawPosting`, it hands back a `CollectResult`. It never persists, never
normalizes, never decides cadence — that is `store`, `normalize`, and the
`runtime` scheduler's job respectively.
"""

from typing import Protocol

from jobtracker.collect.http import HttpSession
from jobtracker.core.enums import Source
from jobtracker.core.models import Board, CollectResult


class Collector(Protocol):
    source: Source

    def fetch(self, board: Board, session: HttpSession) -> CollectResult: ...
