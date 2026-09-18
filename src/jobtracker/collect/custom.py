"""One function per company with no known ATS — blueprint/wp/WP06-collect-ats2.md §4.

Each entry in `_HANDLERS` is a debt, and it is commented as one: why this
particular company has no ATS family, and where its board actually lives.
Prefer JSON embedded in the page's HTML over DOM scraping — a redesign
breaks CSS selectors, not an embedded JSON blob — and never reach for a
headless browser (interdit n°9) before trying `curl_cffi` against whatever
the page's own network calls turn out to be.

As of this lot, every company in `configs/companies.yaml` maps to a known
ATS family (some `enabled: false` pending recon, none `source: custom`), so
`_HANDLERS` is empty — this module exists so the wiring and its failure mode
are already in place the day the first genuinely ATS-less company is added.
Past ~20 entries here, that is itself a signal a whole ATS family was missed
(blueprint/11-SOURCES.md §3), not that this file should keep growing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from jobtracker.collect.http import HttpSession
from jobtracker.core.enums import Source
from jobtracker.core.errors import BoardNotFound
from jobtracker.core.models import Board, CollectResult

_HANDLERS: Mapping[str, Callable[[Board, HttpSession], CollectResult]] = {}


class CustomCollector:
    source = Source.CUSTOM

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        handler = _HANDLERS.get(board.company_slug)
        if handler is None:
            raise BoardNotFound(
                f"custom: no handler registered for {board.company_slug!r} — "
                "the registry says source: custom but collect/custom.py has no "
                "matching function"
            )
        return handler(board, session)
