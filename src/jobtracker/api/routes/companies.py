"""`GET /companies` — blueprint/03-INTERFACES.md §3.6."""

from fastapi import APIRouter

from jobtracker.api.deps import Conn
from jobtracker.api.schemas import CompanyOut
from jobtracker.store.companies import list_companies
from jobtracker.store.postings import count_active_by_company

router = APIRouter(tags=["companies"])


@router.get("/companies")
def get_companies(
    conn: Conn, sector: str | None = None, country: str | None = None
) -> list[CompanyOut]:
    counts = count_active_by_company(conn)
    return [
        CompanyOut(
            company_slug=c.company_slug,
            company_name=c.company_name,
            sector=c.sector,
            hq_country=c.hq_country,
            source=c.source,
            enabled=c.enabled,
            postings_count=counts.get(c.company_slug, 0),
            last_ok_at=c.last_ok_at.isoformat() if c.last_ok_at else None,
        )
        for c in list_companies(conn, sector=sector, country=country)
    ]
