"""`custom` collector tests — blueprint/wp/WP06-collect-ats2.md §4.

Two dispatch paths: a hand-written handler per company, and the generic rendered
listing driven by `extra.link`. The session is a fake that returns canned DOMs, so
nothing here starts a browser — `collect/browser.py` is exercised by the `live` test.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from factories_collect import FakeHttpSession
from jobtracker.collect import custom
from jobtracker.collect.custom import CustomCollector, KnownCustomPosting
from jobtracker.collect.http import BUDGET_EXHAUSTED, HttpSession
from jobtracker.core.enums import Source
from jobtracker.core.errors import BoardNotFound, ConfigError, SourceUnavailable
from jobtracker.core.models import Board, CollectResult

pytestmark = pytest.mark.contract

_LISTING = "https://shop.example/careers"
_LINK = r"shop\.example/careers/details/([a-z0-9-]+)"


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


def _listing_board(**extra: str) -> Board:
    return _board(token=_LISTING, extra={"link": _LINK, **extra})


@dataclass
class _Pages:
    """An `HttpSession` serving canned rendered DOMs by URL; `""` is a spent budget."""

    pages: Mapping[str, str]
    calls: list[str] = field(default_factory=list)

    def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str:
        self.calls.append(url)
        if url not in self.pages:
            raise BoardNotFound(f"404 for {url}")
        return self.pages[url]

    def get_json(self, url: str, *, params: Mapping[str, str] | None = None) -> object:
        raise AssertionError("the rendered listing only reads pages")

    def post_json(self, url: str, *, json: Mapping[str, object]) -> object:
        raise AssertionError("the rendered listing only reads pages")


def _card(slug: str, title: str, location: str) -> str:
    return (
        f'<li><a href="/careers/details/{slug}/"><h3>{title}</h3><span>{location}</span></a>'
        f'<a href="/careers/details/{slug}/#apply">Apply now</a></li>'
    )


def _detail(title: str, body: str) -> str:
    return (
        "<html><head><style>h1{color:red}</style><script>track()</script></head><body>"
        f"<nav><a href='/'>Home</a></nav><main><h1>{title}</h1><p>{body}</p></main>"
        "<footer>© Shop</footer></body></html>"
    )


_QUANT = "https://shop.example/careers/details/quant-dev/"
_TRADER = "https://shop.example/careers/details/trader/"
_PAGES = {
    _LISTING: "<ul>"
    + _card("quant-dev", "Quantitative Developer", "London")
    + _card("trader", "Trader", "Chicago")
    + '<a href="/about">About</a></ul>',
    _QUANT: _detail("Quantitative Developer", "C++ and Python. 0-2 years."),
    _TRADER: _detail("Trader", "Options market making."),
}


def test_unregistered_slug_without_a_link_raises_board_not_found() -> None:
    with pytest.raises(BoardNotFound):
        CustomCollector().fetch(_board(), FakeHttpSession())


def test_registered_handler_is_dispatched_to(monkeypatch: pytest.MonkeyPatch) -> None:
    board = _board()

    def _handler(board: Board, session: HttpSession) -> CollectResult:
        return CollectResult(
            board=board, postings=(), requests_made=1, duration_ms=0, truncated=False
        )

    monkeypatch.setitem(custom._HANDLERS, board.company_slug, _handler)  # type: ignore[index]
    result = CustomCollector().fetch(board, FakeHttpSession())
    assert result.requests_made == 1


def test_rendered_listing_yields_one_posting_per_matching_link() -> None:
    session = _Pages(_PAGES)
    result = CustomCollector().fetch(_listing_board(), session)

    assert [p.source_job_id for p in result.postings] == ["quant-dev", "trader"]
    quant = result.postings[0]
    assert quant.title_raw == "Quantitative Developer"
    assert quant.location_raw == "London"
    assert quant.url == _QUANT
    assert "C++ and Python. 0-2 years." in quant.description_raw
    # Chrome around the posting is not its description.
    for noise in ("track()", "color:red", "Home", "© Shop"):
        assert noise not in quant.description_raw
    assert result.requests_made == 3  # one listing + two details
    assert result.truncated is False


def test_description_prefers_the_main_element_when_the_page_has_one() -> None:
    body = "Build the pricing library. " * 12
    chrome = "<div class='menu'><a href='/who'>Who We Are</a><p>Office Locations</p></div>"
    pages = dict(_PAGES)
    title = "<header><h1>Quantitative Developer</h1></header>"
    pages[_QUANT] = f"<body>{chrome}{title}<main><p>{body}</p></main></body>"
    result = CustomCollector().fetch(_listing_board(title="heading"), _Pages(pages))
    quant = result.postings[0]
    assert quant.title_raw == "Quantitative Developer"  # read even though it sits in <header>
    assert quant.description_raw.startswith("Build the pricing library.")
    assert "Office Locations" not in quant.description_raw


def test_a_stored_posting_is_not_opened_again() -> None:
    session = _Pages(_PAGES)
    known = {
        ("some_bespoke_shop", "quant-dev"): KnownCustomPosting(
            "Quantitative Developer", "London", "stored description"
        )
    }
    result = CustomCollector(known=known).fetch(_listing_board(), session)

    assert _QUANT not in session.calls
    assert result.postings[0].description_raw == "stored description"
    assert result.requests_made == 2
    # Same inputs, same hash: an unchanged posting must not read as an update.
    again = CustomCollector(known=known).fetch(_listing_board(), _Pages(_PAGES))
    assert again.postings[0].content_hash == result.postings[0].content_hash


def test_title_heading_takes_the_detail_page_h1() -> None:
    pages = dict(_PAGES)
    pages[_LISTING] = '<a href="/careers/details/quant-dev/"><b>NEW</b> Quantitative Dev…</a>'
    result = CustomCollector().fetch(_listing_board(title="heading"), _Pages(pages))
    assert result.postings[0].title_raw == "Quantitative Developer"
    assert result.postings[0].location_raw is None


def test_a_card_linked_only_by_a_button_is_named_by_its_page() -> None:
    pages = dict(_PAGES)
    pages[_LISTING] = '<a href="/careers/details/trader/">Learn more</a>'
    result = CustomCollector().fetch(_listing_board(), _Pages(pages))
    assert [p.title_raw for p in result.postings] == ["Trader"]


def test_pagination_stops_at_the_first_page_that_adds_nothing() -> None:
    template = "https://shop.example/careers?page={page}"
    pages = {
        "https://shop.example/careers?page=1": _card("quant-dev", "Quantitative Developer", "X"),
        "https://shop.example/careers?page=2": _card("trader", "Trader", "Y"),
        "https://shop.example/careers?page=3": _card("trader", "Trader", "Y"),
        _QUANT: _PAGES[_QUANT],
        _TRADER: _PAGES[_TRADER],
    }
    session = _Pages(pages)
    board = _board(token=template, extra={"link": _LINK, "pages": "9"})
    result = CustomCollector().fetch(board, session)

    assert len(result.postings) == 2
    assert "https://shop.example/careers?page=4" not in session.calls


def test_a_page_that_rendered_empty_mid_listing_gets_a_second_look() -> None:
    template = "https://shop.example/careers?page={page}"
    second = "https://shop.example/careers?page=2"

    @dataclass
    class _SlowSecondPage(_Pages):
        def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str:
            first_look = url == second and second not in self.calls
            body = super().get_text(url, params=params)
            return "<p>Loading…</p>" if first_look else body

    pages = {
        "https://shop.example/careers?page=1": _card("quant-dev", "Quantitative Developer", "X"),
        second: _card("trader", "Trader", "Y"),
        "https://shop.example/careers?page=3": "<p>No more results</p>",
        _QUANT: _PAGES[_QUANT],
        _TRADER: _PAGES[_TRADER],
    }
    session = _SlowSecondPage(pages)
    board = _board(token=template, extra={"link": _LINK, "pages": "9"})
    result = CustomCollector().fetch(board, session)

    assert [p.source_job_id for p in result.postings] == ["quant-dev", "trader"]
    assert session.calls.count(second) == 2
    assert "https://shop.example/careers?page=4" not in session.calls


def test_a_page_still_showing_the_first_page_gets_a_second_look() -> None:
    # A listing drawn by script shows its default cards before the page asked for arrives.
    template = "https://shop.example/careers?page={page}"
    first, second = template.replace("{page}", "1"), template.replace("{page}", "2")

    @dataclass
    class _StaleSecondPage(_Pages):
        def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str:
            stale = url == second and second not in self.calls
            body = super().get_text(url, params=params)
            return self.pages[first] if stale else body

    pages = {
        first: _card("quant-dev", "Quantitative Developer", "X"),
        second: _card("trader", "Trader", "Y"),
        _QUANT: _PAGES[_QUANT],
        _TRADER: _PAGES[_TRADER],
    }
    board = _board(token=template, extra={"link": _LINK, "pages": "2"})
    result = CustomCollector().fetch(board, _StaleSecondPage(pages))
    assert [p.source_job_id for p in result.postings] == ["quant-dev", "trader"]


def test_a_listing_page_that_will_not_load_keeps_the_pages_already_read() -> None:
    template = "https://shop.example/careers?page={page}"
    second = "https://shop.example/careers?page=2"

    @dataclass
    class _DeadSecondPage(_Pages):
        def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str:
            if url == second:
                self.calls.append(url)
                raise SourceUnavailable("timeout")
            return super().get_text(url, params=params)

    pages = {
        "https://shop.example/careers?page=1": _card("quant-dev", "Quantitative Developer", "X"),
        _QUANT: _PAGES[_QUANT],
    }
    session = _DeadSecondPage(pages)
    board = _board(token=template, extra={"link": _LINK, "pages": "9"})
    result = CustomCollector().fetch(board, session)

    assert [p.source_job_id for p in result.postings] == ["quant-dev"]
    assert session.calls.count(second) == 2  # asked again before giving up
    assert result.truncated is True  # so nothing is deactivated on a partial listing


def test_the_first_listing_page_failing_is_the_board_failing() -> None:
    @dataclass
    class _Dead(_Pages):
        def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str:
            raise SourceUnavailable("timeout")

    with pytest.raises(SourceUnavailable):
        CustomCollector().fetch(_listing_board(), _Dead({}))


def test_a_vanished_detail_page_drops_only_that_posting() -> None:
    pages = {k: v for k, v in _PAGES.items() if k != _TRADER}
    result = CustomCollector().fetch(_listing_board(), _Pages(pages))
    assert [p.source_job_id for p in result.postings] == ["quant-dev"]


def test_a_spent_budget_marks_the_result_truncated() -> None:
    pages = dict(_PAGES)
    pages[_TRADER] = ""  # what PolicedHttpSession.get_text returns once the budget is spent
    result = CustomCollector().fetch(_listing_board(), _Pages(pages))
    assert [p.source_job_id for p in result.postings] == ["quant-dev"]
    assert result.truncated is True


def test_a_listing_with_no_matching_link_is_empty_not_an_error() -> None:
    result = CustomCollector().fetch(_listing_board(), _Pages({_LISTING: "<a href='/x'>x</a>"}))
    assert result.postings == ()
    assert result.truncated is False


@pytest.mark.parametrize(
    "board",
    [
        _board(token="not-a-url", extra={"link": _LINK}),
        _board(token=_LISTING, extra={"link": "("}),
        _board(token=_LISTING + "?p={page}", extra={"link": _LINK, "pages": "many"}),
    ],
)
def test_a_malformed_entry_is_a_config_error(board: Board) -> None:
    with pytest.raises(ConfigError):
        CustomCollector().fetch(board, _Pages(_PAGES))


def test_a_title_that_cannot_matter_is_kept_without_opening_its_page() -> None:
    pages = dict(_PAGES)
    pages[_LISTING] = _card("quant-dev", "Quantitative Developer", "London") + _card(
        "teller", "Branch Teller", "Leeds"
    )
    session = _Pages(pages)
    result = CustomCollector().fetch(_listing_board(), session)

    teller = result.postings[1]
    assert (teller.title_raw, teller.location_raw, teller.description_raw) == (
        "Branch Teller",
        "Leeds",
        "",
    )
    assert "https://shop.example/careers/details/teller/" not in session.calls


def test_title_line_skips_the_badge_a_card_leads_with() -> None:
    pages = dict(_PAGES)
    pages[_LISTING] = (
        '<a href="/careers/details/quant-dev/"><span>Permanent</span>'
        "<h3>Quantitative Developer</h3><span>Paris</span></a>"
    )
    result = CustomCollector().fetch(_listing_board(title_line="2"), _Pages(pages))
    assert (result.postings[0].title_raw, result.postings[0].location_raw) == (
        "Quantitative Developer",
        "Paris",
    )


# --- extra.api: the portal's own JSON endpoint --------------------------------

_API = "https://shop.example/api/jobs?offset={offset}&limit={size}"
_API_EXTRA = {
    "api": _API,
    "size": "2",
    "items": "data.items",
    "total": "data.total",
    "id": "id",
    "title": "name",
    "location": "city,sites.country",
    "posted": "date",
    "url": "https://shop.example/job/{slug}/{id}",
}


def _job(job_id: int, name: str, **fields: object) -> dict[str, object]:
    return {
        "id": job_id,
        "name": name,
        "slug": name.lower().replace(" ", "-"),
        "city": "Paris",
        "sites": [{"country": "France"}, {"country": "Germany"}],
        "date": "2026-10-01",
        **fields,
    }


def _answer(*jobs: dict[str, object], total: int) -> dict[str, object]:
    return {"data": {"total": total, "items": list(jobs)}}


@dataclass
class _Api:
    """An `HttpSession` answering JSON endpoints and rendered pages by URL."""

    json: Mapping[str, object]
    pages: Mapping[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    bodies: list[Mapping[str, object]] = field(default_factory=list)

    def get_json(self, url: str, *, params: Mapping[str, str] | None = None) -> object:
        self.calls.append(url)
        if url not in self.json:
            raise BoardNotFound(f"404 for {url}")
        return self.json[url]

    def post_json(self, url: str, *, json: Mapping[str, object]) -> object:
        self.bodies.append(json)
        return self.get_json(url)

    def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str:
        self.calls.append(url)
        if url not in self.pages:
            raise BoardNotFound(f"404 for {url}")
        return self.pages[url]


def _api_board(**extra: str) -> Board:
    return _board(token=_LISTING, extra={**_API_EXTRA, **extra})


def _page(offset: int) -> str:
    return _API.replace("{offset}", str(offset)).replace("{size}", "2")


def test_api_listing_reads_postings_and_their_description_from_the_answer() -> None:
    session = _Api(
        {
            _page(0): _answer(
                _job(1, "Quant Developer", text="<p>C++</p>"),
                _job(2, "Teller", text="<p>Cash</p>"),
                total=3,
            ),
            _page(2): _answer(_job(3, "Trader", text="<p>Options</p>"), total=3),
        }
    )
    result = CustomCollector().fetch(_api_board(description="text"), session)

    assert [p.source_job_id for p in result.postings] == ["1", "2", "3"]
    first = result.postings[0]
    assert first.title_raw == "Quant Developer"
    assert first.location_raw == "Paris, France, Germany"  # two paths, a list walked through
    assert first.url == "https://shop.example/job/quant-developer/1"
    assert first.posted_at_raw == "2026-10-01"
    assert first.description_raw == "<p>C++</p>"
    # The listing carries the descriptions: even a title nobody wants costs nothing more.
    assert result.postings[1].description_raw == "<p>Cash</p>"
    assert session.calls == [_page(0), _page(2)]  # `total` reached: no third call
    assert (result.requests_made, result.truncated) == (2, False)


def test_api_listing_stops_at_a_page_that_adds_nothing_when_no_total_is_given() -> None:
    session = _Api(
        {
            _page(0): _answer(_job(1, "Quant Developer", text="a"), total=0),
            _page(2): _answer(_job(1, "Quant Developer", text="a"), total=0),
        }
    )
    extra = {k: v for k, v in _API_EXTRA.items() if k != "total"}
    board = _board(token=_LISTING, extra={**extra, "description": "text"})
    result = CustomCollector().fetch(board, session)
    assert len(result.postings) == 1
    assert _page(4) not in session.calls


def test_an_api_page_that_answers_short_once_is_asked_again() -> None:
    @dataclass
    class _ShortOnce(_Api):
        def get_json(self, url: str, *, params: Mapping[str, str] | None = None) -> object:
            first_look = url == _page(2) and url not in self.calls
            answer = super().get_json(url, params=params)
            return _answer(total=3) if first_look else answer

    session = _ShortOnce(
        {
            _page(0): _answer(
                _job(1, "Quant Developer", text="a"), _job(2, "T", text="b"), total=3
            ),
            _page(2): _answer(_job(3, "Trader", text="c"), total=3),
        }
    )
    result = CustomCollector().fetch(_api_board(description="text"), session)
    assert [p.source_job_id for p in result.postings] == ["1", "2", "3"]
    assert result.truncated is False


def test_a_page_of_postings_already_seen_does_not_end_a_walk_with_a_total() -> None:
    # An endpoint whose order is not stable repeats postings from one page to the next.
    session = _Api(
        {
            _page(0): _answer(
                _job(1, "Quant Developer", text="a"), _job(2, "T", text="b"), total=5
            ),
            _page(2): _answer(
                _job(1, "Quant Developer", text="a"), _job(2, "T", text="b"), total=5
            ),
            _page(4): _answer(_job(3, "Trader", text="c"), total=5),
        }
    )
    result = CustomCollector().fetch(_api_board(description="text"), session)
    assert [p.source_job_id for p in result.postings] == ["1", "2", "3"]
    assert _page(6) not in session.calls  # the announced total is walked, no further
    assert result.truncated is True  # 3 of the 5 announced: not seen whole


def test_an_api_listing_that_stops_short_of_its_announced_total_is_truncated() -> None:
    # 2 postings listed out of 40 announced: whatever stopped the walk, nothing may be
    # deactivated on the strength of it.
    session = _Api(
        {
            _page(0): _answer(
                _job(1, "Quant Developer", text="a"), _job(2, "T", text="b"), total=40
            ),
            _page(2): _answer(total=40),
        }
    )
    result = CustomCollector().fetch(_api_board(description="text"), session)
    assert len(result.postings) == 2
    assert result.truncated is True


def test_api_post_body_carries_the_page_placeholders() -> None:
    url = "https://shop.example/api/search"
    session = _Api({url: _answer(_job(1, "Quant Developer", text="a"), total=1)})
    board = _api_board(
        api=url, body='{"from": {offset}, "size": {size}, "page": "{page}"}', description="text"
    )
    CustomCollector().fetch(board, session)
    assert session.bodies == [{"from": 0, "size": 2, "page": "0"}]


def test_api_detail_endpoint_is_called_once_per_title_that_could_matter() -> None:
    detail = "https://shop.example/api/job/{id}"
    session = _Api(
        {
            _page(0): _answer(_job(1, "Quant Developer"), _job(2, "Branch Teller"), total=2),
            "https://shop.example/api/job/1": {"job": {"body": "<p>C++</p>", "extra": "0-2 years"}},
        }
    )
    board = _api_board(detail=detail, detail_description="job.body,job.extra")
    result = CustomCollector().fetch(board, session)

    assert result.postings[0].description_raw == "<p>C++</p>\n\n0-2 years"
    assert result.postings[1].description_raw == ""  # kept, never asked about
    assert "https://shop.example/api/job/2" not in session.calls
    assert result.requests_made == 2


def test_api_listing_without_a_description_renders_the_posting_page() -> None:
    session = _Api(
        {_page(0): _answer(_job(1, "Quant Developer"), total=1)},
        pages={"https://shop.example/job/quant-developer/1": _detail("Quant Developer", "C++.")},
    )
    result = CustomCollector().fetch(_api_board(), session)
    assert "C++." in result.postings[0].description_raw


def test_api_listing_reuses_a_stored_description() -> None:
    session = _Api({_page(0): _answer(_job(1, "Quant Developer"), total=1)})
    known = {("some_bespoke_shop", "1"): KnownCustomPosting("Quant Developer", "Paris", "stored")}
    result = CustomCollector(known=known).fetch(_api_board(), session)
    assert result.postings[0].description_raw == "stored"
    assert session.calls == [_page(0)]


def test_api_fields_can_be_picked_from_a_list_of_key_value_pairs() -> None:
    item = {
        "Link": "https://shop.example/job/9",
        "Questions": [
            {"QuestionName": "reqid", "Value": "9"},
            {"QuestionName": "jobtitle", "Value": "Quant Developer"},
        ],
    }
    url = "https://shop.example/api/search"
    session = _Api({url: {"Jobs": {"Job": [item]}}})
    board = _board(
        token=_LISTING,
        extra={
            "api": url,
            "items": "Jobs.Job",
            "id": "Questions.QuestionName=reqid.Value",
            "title": "Questions.QuestionName=jobtitle.Value",
            "url": "{Link}",
            "description": "Questions.QuestionName=jobtitle.Value",
        },
    )
    result = CustomCollector().fetch(board, session)
    assert [(p.source_job_id, p.title_raw, p.url) for p in result.postings] == [
        ("9", "Quant Developer", "https://shop.example/job/9")
    ]


def test_an_api_answer_that_is_a_bare_list_is_read_from_its_root() -> None:
    url = "https://shop.example/jobPublication/list.json"
    session = _Api({url: [{"id": 7, "position": "Quant Analyst", "url": "https://shop.example/7"}]})
    board = _board(
        token=_LISTING,
        extra={"api": url, "items": ".", "id": "id", "title": "position", "url": "{url}"},
    )
    result = CustomCollector().fetch(board, session)
    assert [(p.source_job_id, p.title_raw) for p in result.postings] == [("7", "Quant Analyst")]


def test_an_api_answer_with_no_postings_is_empty_not_an_error() -> None:
    result = CustomCollector().fetch(
        _api_board(description="text"), _Api({_page(0): {"unexpected": True}})
    )
    assert result.postings == ()
    assert result.truncated is False


def test_a_spent_budget_on_the_api_listing_marks_the_result_truncated() -> None:
    session = _Api(
        {
            _page(0): _answer(_job(1, "Quant Developer", text="a"), total=9),
            _page(2): BUDGET_EXHAUSTED,
        }
    )
    result = CustomCollector().fetch(_api_board(description="text"), session)
    assert len(result.postings) == 1
    assert result.truncated is True  # the rest of the listing was not seen


@pytest.mark.parametrize(
    "extra",
    [
        {"items": ""},
        {"size": "many"},
        {"body": "{not json"},
        {"detail": "https://shop.example/api/job/{id}"},  # no detail_description
        {"api": "shop.example/api"},
    ],
)
def test_a_malformed_api_entry_is_a_config_error(extra: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        CustomCollector().fetch(_api_board(**extra), _Api({}))
