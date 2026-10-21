"""`GET /postings`, `GET /postings/{id}`, the user's writes on a posting (favorite, hide,
triage, application status, note) — blueprint/03-INTERFACES.md §3.6 — and the offer as a PDF
(blueprint/wp/WP21-applications.md §4).
"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response

from jobtracker.api.deps import Conn, get_posting_filter
from jobtracker.api.schemas import (
    AliasOut,
    FlagRequest,
    LlmCorrectionOut,
    NoteRequest,
    PostingDetailOut,
    PostingOut,
    PostingsPage,
    StatusRequest,
    TriageRequest,
)
from jobtracker.api.tracking import OFFER_PDF, offer_sheet, render_pending, track_posting
from jobtracker.career import offer
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Track
from jobtracker.core.errors import RenderError, StorageError
from jobtracker.store.applications import application_for_posting
from jobtracker.store.llm_reviews import current_corrections
from jobtracker.store.postings import (
    PostingFilter,
    SortKey,
    get_posting_row,
    get_verdict,
    list_aliases,
    list_postings,
    mark_favorite,
    mark_hidden,
    set_note,
    set_triage,
)
from jobtracker.store.search import get_description
from jobtracker.store.tracks import get_track_verdict

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
def get_posting_detail(posting_id: str, conn: Conn, track: Track | None = None) -> PostingDetailOut:
    """With `track`, the score, tier and reasons are that track's — when it scored the posting."""
    row = get_posting_row(conn, posting_id, track=track)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no such posting: {posting_id!r}")
    verdict = (get_track_verdict(conn, track, posting_id) if track is not None else None) or (
        get_verdict(conn, posting_id)
    )
    aliases = tuple(AliasOut.from_row(a) for a in list_aliases(conn, posting_id))
    base = PostingOut.from_row(row)
    return PostingDetailOut(
        **base.model_dump(),
        description=get_description(conn, posting_id),
        note=row.note,
        reasons=verdict.reasons if verdict is not None else (),
        aliases=aliases,
        llm_corrections=tuple(
            LlmCorrectionOut(**c.model_dump()) for c in current_corrections(conn, posting_id)
        ),
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


@router.post("/postings/{posting_id}/triage", status_code=204)
def triage_posting(posting_id: str, body: TriageRequest, conn: Conn) -> Response:
    if get_posting_row(conn, posting_id) is None:
        raise HTTPException(status_code=404, detail=f"no such posting: {posting_id!r}")
    set_triage(conn, posting_id, body.triage)
    conn.commit()
    return Response(status_code=204)


@router.post("/postings/{posting_id}/status", status_code=204)
def set_status(
    posting_id: str,
    body: StatusRequest,
    conn: Conn,
    request: Request,
    background: BackgroundTasks,
) -> Response:
    """The posting's application (WP21 §2.2): created on the first status, with the offer
    archived as a PDF once the response is sent; `null` stops tracking."""
    row = get_posting_row(conn, posting_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no such posting: {posting_id!r}")
    today = utc_now().date()
    tracked = track_posting(
        conn,
        row,
        body.status,
        today=today,
        career_root=request.app.state.career_root,
        aliases=request.app.state.company_aliases,
    )
    if tracked.pdf is not None:
        background.add_task(render_pending, tracked.pdf, today=today)
    return Response(status_code=204)


@router.get(
    "/postings/{posting_id}/offer.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_offer_pdf(posting_id: str, conn: Conn, request: Request) -> Response:
    """The offer as a clean PDF: the copy archived when you applied, else rendered now."""
    row = get_posting_row(conn, posting_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no such posting: {posting_id!r}")
    application = application_for_posting(conn, posting_id)
    archived = (
        request.app.state.career_root / "applications" / application.dossier / OFFER_PDF
        if application is not None and application.dossier
        else None
    )
    if archived is not None and archived.is_file():
        pdf = archived.read_bytes()
    else:
        applied_on = application.applied_on if application is not None else None
        sheet = offer_sheet(conn, row, applied_on)
        try:
            pdf = offer.html_to_pdf(offer.offer_html(sheet, archived_on=utc_now().date()))
        except RenderError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    filename = f"{row.company_name} - {row.title_raw}.pdf".replace('"', "'")
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}"},
    )


@router.post("/postings/{posting_id}/note", status_code=204)
def save_note(posting_id: str, body: NoteRequest, conn: Conn) -> Response:
    if get_posting_row(conn, posting_id) is None:
        raise HTTPException(status_code=404, detail=f"no such posting: {posting_id!r}")
    set_note(conn, posting_id, body.note)
    conn.commit()
    return Response(status_code=204)
