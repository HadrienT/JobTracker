"""`/cvs` — the CV registry (blueprint/wp/WP22-cvs.md §4).

A CV is uploaded like an application's file: the raw request body, its name in the query string.
Sending the same bytes twice gives the same CV.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from jobtracker.api.deps import Conn, read_upload
from jobtracker.api.schemas import CvEditRequest, CvOut
from jobtracker.api.tracking import register_cv, safe_file_name
from jobtracker.career.cvs import cv_path
from jobtracker.core.models import Cv
from jobtracker.store.cvs import current_cv_id, edit_cv, get_cv, list_cvs

router = APIRouter(tags=["cvs"])


def _found(conn: Conn, cv_id: str) -> Cv:
    cv = get_cv(conn, cv_id)
    if cv is None:
        raise HTTPException(status_code=404, detail=f"no such CV: {cv_id!r}")
    return cv


def _out(conn: Conn, cv: Cv) -> CvOut:
    return CvOut.from_cv(cv, current=cv.cv_id == current_cv_id(conn))


@router.get("/cvs")
def get_cvs(conn: Conn) -> list[CvOut]:
    """Every CV, newest first; `pinned` are the versions, `current` the one to assume next."""
    current = current_cv_id(conn)
    return [CvOut.from_cv(cv, current=cv.cv_id == current) for cv in list_cvs(conn)]


@router.post("/cvs", status_code=201)
async def post_cv(
    name: Annotated[str, Query(min_length=1, max_length=200)],
    conn: Conn,
    request: Request,
) -> CvOut:
    """Add a version: the raw PDF, named by `name`."""
    data = await read_upload(request)
    try:
        cv_id = register_cv(conn, request.app.state.career_root, data, safe_file_name(name))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    conn.commit()
    return _out(conn, _found(conn, cv_id))


@router.post("/cvs/{cv_id}/edit")
def post_cv_edit(cv_id: str, body: CvEditRequest, conn: Conn) -> CvOut:
    edit_cv(conn, _found(conn, cv_id).cv_id, label=body.label, pinned=body.pinned)
    conn.commit()
    return _out(conn, _found(conn, cv_id))


@router.get(
    "/cvs/{cv_id}/file",
    response_class=FileResponse,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_cv_file(cv_id: str, conn: Conn, request: Request) -> FileResponse:
    """The PDF itself, shown inline. The id comes from the table, never from the path as given."""
    cv = _found(conn, cv_id)
    target = cv_path(request.app.state.career_root, cv.cv_id)
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"file missing for CV {cv_id!r}")
    return FileResponse(
        target,
        media_type="application/pdf",
        content_disposition_type="inline",
        filename=cv.file_name,
    )
