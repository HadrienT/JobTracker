"""`custom` collector dispatch tests — blueprint/wp/WP06-collect-ats2.md §4.

No company currently has `source: custom` in configs/companies.yaml (every
seeded entry maps to a known ATS family), so this only exercises the
dispatch mechanism itself: an unregistered slug fails loudly rather than
silently returning zero postings, and a registered handler is actually
called.
"""

import pytest

from factories_collect import FakeHttpSession
from jobtracker.collect import custom
from jobtracker.collect.http import HttpSession
from jobtracker.core.enums import Source
from jobtracker.core.errors import BoardNotFound
from jobtracker.core.models import Board, CollectResult

pytestmark = pytest.mark.contract


def _board(**overrides: object) -> Board:
    base: dict[str, object] = {
        "company_slug": "some_bespoke_shop",
        "company_name": "Some Bespoke Shop",
        "source": Source.CUSTOM,
        "token": "",
        "sector": "prop_trading",
        "hq_country": "US",
        "priority": 3,
        "enabled": True,
    }
    base.update(overrides)
    return Board(**base)  # type: ignore[arg-type]


def test_unregistered_slug_raises_board_not_found() -> None:
    with pytest.raises(BoardNotFound):
        custom.CustomCollector().fetch(_board(), FakeHttpSession())


def test_registered_handler_is_dispatched_to(monkeypatch: pytest.MonkeyPatch) -> None:
    board = _board()

    def _handler(board: Board, session: HttpSession) -> CollectResult:
        return CollectResult(
            board=board, postings=(), requests_made=1, duration_ms=0, truncated=False
        )

    monkeypatch.setitem(custom._HANDLERS, board.company_slug, _handler)
    result = custom.CustomCollector().fetch(board, FakeHttpSession())
    assert result.requests_made == 1
