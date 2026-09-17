import sqlite3

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.models import Location
from jobtracker.store.companies import sync_companies
from jobtracker.store.facets import facet_counts
from jobtracker.store.postings import PostingFilter, upsert_posting

pytestmark = pytest.mark.db


def _seed(conn: sqlite3.Connection) -> None:
    sync_companies(
        conn,
        [
            make_board(company_slug="acme_fr", company_name="Acme FR", hq_country="FR"),
            make_board(company_slug="acme_us", company_name="Acme US", hq_country="US"),
        ],
    )
    postings = [
        ("p-fr-cpp", "acme_fr", "FR", frozenset({"cpp"})),
        ("p-fr-python", "acme_fr", "FR", frozenset({"python"})),
        ("p-us-cpp", "acme_us", "US", frozenset({"cpp"})),
    ]
    for posting_id, company_slug, country, tech in postings:
        posting = make_posting(
            posting_id=posting_id,
            source_job_id=posting_id,
            fingerprint=f"fp-{posting_id}",
            company_slug=company_slug,
            locations=(
                Location(city=None, country=country, region=None, remote_mode="onsite", raw=None),
            ),
            tech=tech,
        )
        upsert_posting(conn, posting, make_verdict(posting_id=posting_id))
    conn.commit()


def test_i6_selecting_a_country_does_not_zero_out_other_countries(
    store_conn: sqlite3.Connection,
) -> None:
    _seed(store_conn)

    counts = facet_counts(store_conn, PostingFilter(countries=frozenset({"FR"})))

    assert counts.countries == {"FR": 2, "US": 1}


def test_i6_selecting_a_tech_does_not_zero_out_other_tech(store_conn: sqlite3.Connection) -> None:
    _seed(store_conn)

    counts = facet_counts(store_conn, PostingFilter(tech_any=frozenset({"cpp"})))

    assert counts.tech == {"cpp": 2, "python": 1}


def test_facets_respect_filters_on_other_dimensions(store_conn: sqlite3.Connection) -> None:
    _seed(store_conn)

    counts = facet_counts(store_conn, PostingFilter(countries=frozenset({"FR"})))

    # tech facet is counted *with* the country filter applied (just not with
    # its own dimension), so only the two French postings' tech shows up.
    assert counts.tech == {"cpp": 1, "python": 1}
