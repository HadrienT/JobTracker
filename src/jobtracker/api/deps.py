"""Per-request dependencies — the only place `api` touches a live connection.

`get_conn` reads the connection `app.py`'s lifespan opened once at startup;
no route opens its own. `get_posting_filter` is the one place query
parameters become a `PostingFilter` — shared by `/postings` and `/facets` so
the two can never drift apart on what a given filter means.
"""

import sqlite3
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request

from jobtracker.core.enums import (
    ApplicationStatus,
    RemoteMode,
    RoleFamily,
    Seniority,
    Source,
    Tier,
    Track,
    Triage,
    VisaStatus,
)
from jobtracker.store.postings import PostingFilter

_DEFAULT_VISA = [VisaStatus.SPONSORS, VisaStatus.UNKNOWN]
_DEFAULT_TIERS = [Tier.STRONG, Tier.POSSIBLE, Tier.STRETCH]


def get_conn(request: Request) -> sqlite3.Connection:
    conn: sqlite3.Connection = request.app.state.conn
    return conn


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]

# An uploaded file is a CV, a letter, a screenshot: a few MB at most.
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


async def read_upload(request: Request) -> bytes:
    """The raw request body of a file upload, bounded."""
    declared = int(request.headers.get("content-length") or 0)
    if declared > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (20 MB at most)")
    data = await request.body()
    if not data:
        raise HTTPException(status_code=422, detail="empty file")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (20 MB at most)")
    return data


def get_posting_filter(  # noqa: PLR0917 — one named query param per PostingFilter field
    countries: Annotated[list[str], Query()] = [],  # noqa: B006
    cities: Annotated[list[str], Query()] = [],  # noqa: B006
    statuses: Annotated[list[ApplicationStatus], Query()] = [],  # noqa: B006
    place_country: Annotated[str | None, Query()] = None,
    place_city: Annotated[str | None, Query()] = None,
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
    rejection_reasons: Annotated[list[str], Query()] = [],  # noqa: B006
    posted_within_days: Annotated[int | None, Query(ge=1)] = None,
    query: Annotated[str | None, Query()] = None,
    favorites_only: Annotated[bool, Query()] = False,
    include_hidden: Annotated[bool, Query()] = False,
    triage: Annotated[Triage | None, Query()] = None,
    track: Annotated[Track | None, Query()] = None,
) -> PostingFilter:
    if (place_country is None) != (place_city is None):
        raise HTTPException(
            status_code=422, detail="place_country and place_city go together: one location"
        )
    return PostingFilter(
        place=(place_country, place_city) if place_country and place_city else None,
        statuses=frozenset(statuses),
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
        rejection_reasons=frozenset(rejection_reasons),
        posted_within_days=posted_within_days,
        query=query,
        favorites_only=favorites_only,
        include_hidden=include_hidden,
        triage=triage,
        track=track,
    )
