"""`GET /export/postings.csv` — the current feed, as a spreadsheet.

Same filters and sort as `/postings`, so "what I am looking at" and "what I download" cannot
disagree; the difference is only that it walks every page instead of returning one. Streamed,
so a large feed never sits whole in memory.
"""

import csv
import io
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from jobtracker.api.deps import Conn, get_posting_filter
from jobtracker.store.postings import PostingFilter, PostingRow, SortKey, list_postings

router = APIRouter(tags=["export"])

_PAGE = 100
_COLUMNS = (
    "score",
    "tier",
    "title",
    "company",
    "sector",
    "locations",
    "remote",
    "seniority",
    "min_years",
    "visa",
    "tech",
    "salary",
    "posted_at",
    "first_seen_at",
    "closes_at",
    "application_status",
    "url",
)


def _salary(row: PostingRow) -> str:
    pay = row.compensation
    if pay.amount_min is None and pay.amount_max is None:
        return ""
    low = "" if pay.amount_min is None else str(pay.amount_min)
    high = "" if pay.amount_max is None else str(pay.amount_max)
    span = low if low == high or not high else f"{low}-{high}"
    return " ".join(
        part for part in (span, pay.currency or "", pay.period.value if pay.period else "") if part
    )


def _cells(row: PostingRow) -> list[str]:
    return [
        str(row.score),
        row.tier.value,
        row.title,
        row.company_name,
        row.sector,
        "; ".join(
            ", ".join(part for part in (loc.city, loc.country) if part) or (loc.raw or "")
            for loc in row.locations
        ),
        ", ".join(sorted({loc.remote_mode.value for loc in row.locations})),
        row.seniority.value,
        "" if row.min_years is None else str(row.min_years),
        row.visa_sponsorship.value,
        " ".join(sorted(row.tech)),
        _salary(row),
        row.posted_at_raw or "",
        row.first_seen_at_raw,
        row.closes_at_raw or "",
        row.application_status.value if row.application_status else "",
        row.url,
    ]


def _rows(conn: Conn, flt: PostingFilter, sort: SortKey) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def flush() -> str:
        data = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
        return data

    writer.writerow(_COLUMNS)
    yield flush()
    cursor: str | None = None
    while True:
        page = list_postings(conn, flt, sort, cursor, _PAGE)
        for row in page.items:
            writer.writerow(_cells(row))
        yield flush()
        if page.next_cursor is None:
            return
        cursor = page.next_cursor


@router.get("/export/postings.csv")
def export_postings(
    flt: Annotated[PostingFilter, Depends(get_posting_filter)],
    conn: Conn,
    sort: SortKey = SortKey.SCORE,
) -> StreamingResponse:
    return StreamingResponse(
        _rows(conn, flt, sort),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="jobtracker-postings.csv"'},
    )
