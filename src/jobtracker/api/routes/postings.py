"""`GET /postings`, `GET /postings/{id}`, and the two favorite/hide writes —
blueprint/03-INTERFACES.md §3.6.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from jobtracker.api.deps import Conn, get_posting_filter
from jobtracker.api.schemas import AliasOut, FlagRequest, PostingDetailOut, PostingOut, PostingsPage
from jobtracker.core.errors import StorageError
from jobtracker.store.postings import (
    PostingFilter,
    SortKey,
    get_posting_row,
    get_verdict,
    list_aliases,
    list_postings,
    mark_favorite,
    mark_hidden,
)
from jobtracker.store.search import get_description

router = APIRouter(tags=["postings"])

_MAX_LIMIT = 100


@router.get("/postings")
def get_postings(
    flt: Annotated[PostingFilter, Depends(get_posting_filter)],
    conn: Conn,
    sort: SortKey = SortKey.SCORE,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1)] = 50,
) -> PostingsPage:
    limit = min(limit, _MAX_LIMIT)
    try:
        page = list_postings(conn, flt, sort, cursor, limit)
    except StorageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PostingsPage(
        items=tuple(PostingOut.from_row(row) for row in page.items), next_cursor=page.next_cursor
    )


@router.get("/postings/{posting_id}")
def get_posting_detail(posting_id: str, conn: Conn) -> PostingDetailOut:
    row = get_posting_row(conn, posting_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no such posting: {posting_id!r}")
    verdict = get_verdict(conn, posting_id)
    aliases = tuple(AliasOut.from_row(a) for a in list_aliases(conn, posting_id))
    base = PostingOut.from_row(row)
    return PostingDetailOut(
        **base.model_dump(),
        description=get_description(conn, posting_id),
        reasons=verdict.reasons if verdict is not None else (),
        rejection_reason=verdict.rejection_reason if verdict is not None else None,
        aliases=aliases,
    )


@router.post("/postings/{posting_id}/favorite", status_code=204)
def set_favorite(posting_id: str, body: FlagRequest, conn: Conn) -> Response:
    if get_posting_row(conn, posting_id) is None:
        raise HTTPException(status_code=404, detail=f"no such posting: {posting_id!r}")
    mark_favorite(conn, posting_id, body.value)
    conn.commit()
    return Response(status_code=204)


@router.post("/postings/{posting_id}/hide", status_code=204)
def set_hidden(posting_id: str, body: FlagRequest, conn: Conn) -> Response:
    if get_posting_row(conn, posting_id) is None:
        raise HTTPException(status_code=404, detail=f"no such posting: {posting_id!r}")
    mark_hidden(conn, posting_id, body.value)
    conn.commit()
    return Response(status_code=204)
