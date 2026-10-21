"""`/applications` — the Applications tab (blueprint/wp/WP21-applications.md §6).

Everything the CLI does by hand, over HTTP: list, read, type in, move along, edit, delete,
archive the offer, attach and serve files. The rules live in `store.applications` and
`api.tracking`; this module only maps them to routes. Writes are POSTs (the CORS policy allows
GET and POST only). A file is uploaded as the raw request body with its name in the query
string — no multipart dependency for a single-user tool.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from jobtracker.api.deps import Conn
from jobtracker.api.schemas import (
    ApplicationCreate,
    ApplicationDetailOut,
    ApplicationEditRequest,
    ApplicationEventOut,
    ApplicationFileOut,
    ApplicationOut,
    ApplicationStatusRequest,
    OfferTextRequest,
)
from jobtracker.api.tracking import (
    application_files,
    ensure_folder,
    manual_application,
    offer_pdf_for,
    render_pending,
    resolve_file,
    store_file,
)
from jobtracker.career import offer
from jobtracker.career.names import company_key
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import ApplicationOrigin
from jobtracker.core.errors import RenderError
from jobtracker.core.models import Application
from jobtracker.store.applications import (
    create_application,
    delete_application,
    get_application,
    list_applications,
    record_status,
    update_application,
)
from jobtracker.store.companies import list_companies
from jobtracker.store.postings import get_posting_row, posting_id_by_url

router = APIRouter(tags=["applications"])

# An attached file is a CV, a letter, a screenshot: a few MB at most.
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _found(conn: Conn, application_id: str) -> Application:
    application = get_application(conn, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail=f"no such application: {application_id!r}")
    return application


def _detail(conn: Conn, request: Request, application: Application) -> ApplicationDetailOut:
    today = utc_now().date()
    row = get_posting_row(conn, application.posting_id) if application.posting_id else None
    files = application_files(request.app.state.career_root, application)
    return ApplicationDetailOut(
        **ApplicationOut.from_application(application, today=today).model_dump(),
        events=tuple(
            ApplicationEventOut(on_date=e.on_date, status=e.status, reason=e.reason)
            for e in application.events
        ),
        files=tuple(
            ApplicationFileOut(name=f.name, path=f.relative, kind=f.kind.value, size=f.size)
            for f in files
        ),
        dossier=application.dossier,
        posting_title=row.title_raw if row is not None else None,
        posting_url=row.url if row is not None else None,
    )


def _company_slug(conn: Conn, request: Request, name: str) -> str | None:
    aliases = request.app.state.company_aliases
    key = company_key(name, aliases)
    for company in list_companies(conn):
        if company_key(company.company_name, aliases) == key:
            return company.company_slug
    return None


@router.get("/applications")
def get_applications(conn: Conn) -> list[ApplicationOut]:
    """Every application, newest first — a few hundred rows: the tab filters them itself."""
    today = utc_now().date()
    return [ApplicationOut.from_application(a, today=today) for a in list_applications(conn)]


@router.get("/applications/{application_id}")
def get_application_detail(
    application_id: str, conn: Conn, request: Request
) -> ApplicationDetailOut:
    return _detail(conn, request, _found(conn, application_id))


@router.post("/applications", status_code=201)
def post_application(
    body: ApplicationCreate, conn: Conn, request: Request, background: BackgroundTasks
) -> ApplicationDetailOut:
    """An application typed in. A URL the collector knows links its posting; pasted offer text
    (else that posting) is archived as offer.pdf once the response is sent."""
    today = utc_now().date()
    posting_id = posting_id_by_url(conn, body.url) if body.url else None
    application = manual_application(
        company=body.company,
        title=body.title,
        location=body.location or None,
        applied_on=body.applied_on or today,
        status=body.status,
        note=body.note,
        company_slug=_company_slug(conn, request, body.company),
        origin=ApplicationOrigin.CLI,
        posting_id=posting_id,
    )
    create_application(conn, application)
    conn.commit()
    pending = offer_pdf_for(
        conn, request.app.state.career_root, application, text=body.offer_text, url=body.url
    )
    if pending is not None:
        background.add_task(render_pending, pending, today=today)
    return _detail(conn, request, _found(conn, application.application_id))


@router.post("/applications/{application_id}/status")
def post_application_status(
    application_id: str, body: ApplicationStatusRequest, conn: Conn, request: Request
) -> ApplicationDetailOut:
    application = _found(conn, application_id)
    record_status(
        conn,
        application.application_id,
        body.status,
        on_date=body.on_date or utc_now().date(),
        reason=body.reason,
    )
    conn.commit()
    return _detail(conn, request, _found(conn, application_id))


@router.post("/applications/{application_id}/edit")
def post_application_edit(
    application_id: str, body: ApplicationEditRequest, conn: Conn, request: Request
) -> ApplicationDetailOut:
    application = _found(conn, application_id)
    columns: dict[str, object] = {
        name: value
        for name, value in body.model_dump(exclude_unset=True).items()
        if value is not None or name == "location"
    }
    if "applied_on" in columns:
        columns["applied_on"] = body.applied_on.isoformat() if body.applied_on else None
    if "company" in columns:
        columns["company_slug"] = _company_slug(conn, request, str(columns["company"]))
    if columns:
        update_application(conn, application.application_id, **columns)
        conn.commit()
    return _detail(conn, request, _found(conn, application_id))


@router.post("/applications/{application_id}/delete", status_code=204)
def post_application_delete(application_id: str, conn: Conn) -> Response:
    """The row goes; its folder stays on disk."""
    delete_application(conn, _found(conn, application_id).application_id)
    conn.commit()
    return Response(status_code=204)


@router.post("/applications/{application_id}/offer")
def post_application_offer(
    application_id: str, body: OfferTextRequest, conn: Conn, request: Request
) -> ApplicationDetailOut:
    """(Re)archive offer.pdf now — from the text given, else from the linked posting."""
    application = _found(conn, application_id)
    pending = offer_pdf_for(
        conn, request.app.state.career_root, application, text=body.text, url=body.url
    )
    if pending is None:
        raise HTTPException(
            status_code=422, detail="no offer to archive: paste its text, or link its posting"
        )
    try:
        offer.write_offer_pdf(pending.sheet, pending.target, archived_on=utc_now().date())
    except RenderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _detail(conn, request, _found(conn, application_id))


@router.post("/applications/{application_id}/files", status_code=201)
async def post_application_file(
    application_id: str,
    name: Annotated[str, Query(min_length=1, max_length=200)],
    conn: Conn,
    request: Request,
) -> ApplicationFileOut:
    """Attach a file (the CV sent, a letter, a screenshot): the raw body, named by `name`."""
    application = _found(conn, application_id)
    declared = int(request.headers.get("content-length") or 0)
    if declared > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (20 MB at most)")
    data = await request.body()
    if not data:
        raise HTTPException(status_code=422, detail="empty file")
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large (20 MB at most)")
    career_root = request.app.state.career_root
    folder = ensure_folder(conn, career_root, application)
    try:
        target = store_file(folder, name, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    updated = _found(conn, application_id)
    listed = {f.name: f for f in application_files(career_root, updated)}
    stored = listed[target.name]
    return ApplicationFileOut(
        name=stored.name, path=stored.relative, kind=stored.kind.value, size=stored.size
    )


@router.get(
    "/applications/{application_id}/files/{path:path}",
    response_class=FileResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def get_application_file(
    application_id: str, path: str, conn: Conn, request: Request
) -> FileResponse:
    """One of the application's files, shown inline (PDF, image) — only a listed one."""
    target = resolve_file(request.app.state.career_root, _found(conn, application_id), path)
    if target is None or not target.is_file():
        raise HTTPException(status_code=404, detail=f"no such file: {path!r}")
    return FileResponse(target, content_disposition_type="inline", filename=target.name)
