"""Which recorded application a collected posting is — blueprint/wp/WP21-applications.md §2.2.

Statuses set in the feed before applications existed, and offers applied to by hand and
collected later, both need the same answer: of the unlinked applications at this employer,
which one is this posting? Same employer (registry slug, or the names once normalized — the
history was written by hand), a date within a few days, then title and place decide. A tie
between two applications nothing tells apart (the same job applied to twice) is no tie; any
other is reported, never guessed.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from jobtracker.career.names import company_key, place_agreement, places, title_tokens
from jobtracker.core.models import Application

_DAYS = 4


@dataclass(frozen=True)
class FeedPosting:
    posting_id: str
    company_slug: str
    company_name: str
    title: str
    places: str  # the posting's location labels, joined
    day: date  # when the status was set / the application was made


@dataclass
class FeedLinks:
    links: dict[str, str] = field(default_factory=dict)  # posting_id → application_id
    ambiguous: dict[str, tuple[str, ...]] = field(default_factory=dict)


def _score(posting: FeedPosting, application: Application) -> int | None:
    if application.applied_on is None or abs((application.applied_on - posting.day).days) > _DAYS:
        return None
    total = 0
    left, right = title_tokens(posting.title), title_tokens(application.title or "")
    if left and right:
        overlap = len(left & right)
        total += min(2 * overlap, 6) if overlap else -2
    agreement = place_agreement(places(posting.places), places(application.location or ""))
    total += agreement or 0
    return total if total >= 0 else None


def _twins(left: Application, right: Application) -> bool:
    fields = ("company", "title", "location", "applied_on", "status", "reason")
    return all(getattr(left, name) == getattr(right, name) for name in fields)


def link_postings(
    postings: list[FeedPosting],
    applications: list[Application],
    *,
    aliases: Mapping[str, str],
) -> FeedLinks:
    """Pair postings with applications that have no posting yet, best evidence first."""
    by_slug: dict[str, list[Application]] = defaultdict(list)
    by_key: dict[str, list[Application]] = defaultdict(list)
    for application in applications:
        if application.posting_id is None:
            if application.company_slug:
                by_slug[application.company_slug].append(application)
            by_key[company_key(application.company, aliases)].append(application)

    def employer(posting: FeedPosting) -> list[Application]:
        same = by_slug[posting.company_slug] + by_key[company_key(posting.company_name, aliases)]
        return list({a.application_id: a for a in same}.values())

    by_id = {a.application_id: a for a in applications}
    scored = sorted(
        (
            (points, posting.posting_id, application.application_id)
            for posting in postings
            for application in employer(posting)
            if (points := _score(posting, application)) is not None
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )
    options: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for points, posting_id, application_id in scored:
        options[posting_id].append((points, application_id))
    result = FeedLinks()
    taken: set[str] = set()
    for points, posting_id, application_id in scored:
        if posting_id in result.links or posting_id in result.ambiguous or application_id in taken:
            continue
        rivals = [a for p, a in options[posting_id] if p == points and a != application_id]
        rivals = [
            a for a in rivals if a not in taken and not _twins(by_id[a], by_id[application_id])
        ]
        if rivals:
            result.ambiguous[posting_id] = (application_id, *rivals)
            continue
        result.links[posting_id] = application_id
        taken.add(application_id)
    return result
