"""A collected posting finds the application recorded for it — WP21 §2.2."""

from datetime import date

from jobtracker.career.feedlink import FeedPosting, link_postings
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus
from jobtracker.core.models import Application

_DAY = date(2026, 10, 8)


def _application(application_id: str, **overrides: object) -> Application:
    base: dict[str, object] = {
        "application_id": application_id,
        "company": "Point72",
        "company_slug": None,
        "title": "Quant Dev",
        "location": "UK (London)",
        "applied_on": _DAY,
        "applied_on_estimated": False,
        "closed_on": None,
        "status": ApplicationStatus.APPLIED,
        "reason": "",
        "posting_id": None,
        "dossier": None,
        "origin": ApplicationOrigin.IMPORT,
    }
    base.update(overrides)
    return Application(**base)  # type: ignore[arg-type]


def _posting(posting_id: str, places: str, **overrides: object) -> FeedPosting:
    base: dict[str, object] = {
        "posting_id": posting_id,
        "company_slug": "point72_cubist",
        "company_name": "Point72 / Cubist",
        "title": "Quantitative Developer",
        "places": places,
        "day": _DAY,
    }
    base.update(overrides)
    return FeedPosting(**base)  # type: ignore[arg-type]


_ALIASES = {"point72cubist": "point72", "point72": "point72"}


def test_names_meet_through_aliases_and_places_pick_the_office() -> None:
    applications = [
        _application("london"),
        _application("chicago", location="USA (Chicago) IL"),
    ]
    postings = [_posting("p-chi", "Chicago, US"), _posting("p-lon", "London, GB")]
    links = link_postings(postings, applications, aliases=_ALIASES)
    assert links.links == {"p-chi": "chicago", "p-lon": "london"}


def test_a_date_out_of_the_window_is_another_application() -> None:
    late = _posting("p-lon", "London, GB", day=date(2026, 10, 20))
    assert link_postings([late], [_application("london")], aliases=_ALIASES).links == {}


def test_an_application_already_linked_is_not_offered_again() -> None:
    linked = _application("london", posting_id="p-other")
    assert link_postings([_posting("p-lon", "London, GB")], [linked], aliases=_ALIASES).links == {}


def test_twin_applications_are_no_tie() -> None:
    twins = [_application("first"), _application("second")]
    links = link_postings([_posting("p-lon", "London, GB")], twins, aliases=_ALIASES)
    assert links.links == {"p-lon": "first"}
    assert links.ambiguous == {}


def test_a_real_tie_is_reported() -> None:
    applications = [
        _application("a", location="Remote", status=ApplicationStatus.REJECTED),
        _application("b", location="Remote"),
    ]
    links = link_postings([_posting("p", "")], applications, aliases=_ALIASES)
    assert links.links == {}
    assert set(links.ambiguous["p"]) == {"a", "b"}
