"""`GET /facets` — blueprint/03-INTERFACES.md §3.6, invariant I6.

`facet_counts` already computes each dimension without its own filter
applied (blueprint/wp/WP02-store.md §3) — this route only calls it.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from jobtracker.api.deps import Conn, get_posting_filter
from jobtracker.store.facets import FacetCounts, facet_counts
from jobtracker.store.postings import PostingFilter

router = APIRouter(tags=["facets"])


@router.get("/facets")
def get_facets(
    flt: Annotated[PostingFilter, Depends(get_posting_filter)], conn: Conn
) -> FacetCounts:
    return facet_counts(conn, flt)
