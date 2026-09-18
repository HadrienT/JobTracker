"""Per-request dependencies — the only place `api` touches a live connection.

`get_conn` reads the connection `app.py`'s lifespan opened once at startup;
no route opens its own. `get_posting_filter` is the one place query
parameters become a `PostingFilter` — shared by `/postings` and `/facets` so
the two can never drift apart on what a given filter means.
"""

import sqlite3
from typing import Annotated

from fastapi import Depends, Query, Request

from jobtracker.core.enums import RemoteMode, RoleFamily, Seniority, Source, Tier, VisaStatus
from jobtracker.store.postings import PostingFilter

_DEFAULT_VISA = [VisaStatus.SPONSORS, VisaStatus.UNKNOWN]
_DEFAULT_TIERS = [Tier.STRONG, Tier.POSSIBLE, Tier.STRETCH]


def get_conn(request: Request) -> sqlite3.Connection:
    conn: sqlite3.Connection = request.app.state.conn
    return conn


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def get_posting_filter(  # noqa: PLR0917 — one named query param per PostingFilter field
    countries: Annotated[list[str], Query()] = [],  # noqa: B006
    cities: Annotated[list[str], Query()] = [],  # noqa: B006
    companies: Annotated[list[str], Query()] = [],  # noqa: B006
    sectors: Annotated[list[str], Query()] = [],  # noqa: B006
    sources: Annotated[list[Source], Query()] = [],  # noqa: B006
    role_families: Annotated[list[RoleFamily], Query()] = [],  # noqa: B006
    seniorities: Annotated[list[Seniority], Query()] = [],  # noqa: B006
    remote_modes: Annotated[list[RemoteMode], Query()] = [],  # noqa: B006
    tech_all: Annotated[list[str], Query()] = [],  # noqa: B006
    tech_any: Annotated[list[str], Query()] = [],  # noqa: B006
    visa: Annotated[list[VisaStatus], Query()] = _DEFAULT_VISA,
    min_score: Annotated[int, Query(ge=0, le=100)] = 0,
    tiers: Annotated[list[Tier], Query()] = _DEFAULT_TIERS,
    posted_within_days: Annotated[int | None, Query(ge=1)] = None,
    query: Annotated[str | None, Query()] = None,
    favorites_only: Annotated[bool, Query()] = False,
    include_hidden: Annotated[bool, Query()] = False,
) -> PostingFilter:
    return PostingFilter(
        countries=frozenset(countries),
        cities=frozenset(cities),
        companies=frozenset(companies),
        sectors=frozenset(sectors),
        sources=frozenset(sources),
        role_families=frozenset(role_families),
        seniorities=frozenset(seniorities),
        remote_modes=frozenset(remote_modes),
        tech_all=frozenset(tech_all),
        tech_any=frozenset(tech_any),
        visa=frozenset(visa),
        min_score=min_score,
        tiers=frozenset(tiers),
        posted_within_days=posted_within_days,
        query=query,
        favorites_only=favorites_only,
        include_hidden=include_hidden,
    )
