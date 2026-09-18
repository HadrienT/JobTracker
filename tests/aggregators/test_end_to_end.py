"""An aggregator cycle through the real scheduler and pipeline — WP13 §2 acceptance test.

"Collecter la même offre depuis deux sources et vérifier qu'elle apparaît une fois,
avec un alias." Only the network is faked: the collector, the employer resolver,
`run_source_cycle`, `ingest` and the store are the real ones.
"""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from factories_store import make_board
from jobtracker.collect.aggregators.common import resolver
from jobtracker.collect.aggregators.efinancialcareers import EfcCollector
from jobtracker.collect.http import load_sources_config
from jobtracker.core.enums import Source
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import Board, RawPosting
from jobtracker.match.profile import build_profile
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.runtime.pipeline import ingest
from jobtracker.runtime.scheduler import CycleContext, run_source_cycle
from jobtracker.store.companies import list_discovered, sync_companies
from test_runtime_pipeline import _PROFILE_DATA

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests/fixtures/payloads/efinancialcareers/search.json"


def _pseudo_board() -> Board:
    return Board(
        company_slug="efinancialcareers:quant-us",
        company_name="eFC search",
        source=Source.EFC,
        token="quant developer",
        extra={"country": "US", "max_pages": "1"},
        sector="aggregator",
        hq_country="US",
        priority=1,
        enabled=True,
    )


def _ctx(taxonomy: Taxonomy, geo: GeoIndex, registry: list[Board]) -> CycleContext:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=FIXTURE.read_text())

    return CycleContext(
        sources_config=load_sources_config(REPO_ROOT / "configs" / "sources.yaml"),
        taxonomy=taxonomy,
        geo=geo,
        profile=build_profile(_PROFILE_DATA),
        user_agent="JobTracker/0.1",
        collectors={Source.EFC: EfcCollector()},
        client_factories={Source.EFC: lambda: httpx.Client(transport=httpx.MockTransport(handler))},
        resolve_employer=resolver(registry),
    )


def test_the_same_job_from_an_ats_and_an_aggregator_appears_once_with_an_alias(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex
) -> None:
    job = json.loads(FIXTURE.read_text())["data"][0]
    # The registry knows this employer under a slug that is NOT what slugifying its name gives.
    registry = [make_board(company_slug="oxfordknight", company_name="Oxford Knight Ltd")]
    sync_companies(store_conn, registry)
    store_conn.commit()

    ats = ingest(
        store_conn,
        RawPosting(
            source=Source.GREENHOUSE,
            company_slug="oxfordknight",
            source_job_id="gh-1",
            url="https://boards.greenhouse.io/oxfordknight/jobs/1",
            title_raw=job["title"],
            description_raw="The full ATS description. " * 10,
            location_raw=job["jobLocation"]["displayName"],
            department_raw=None,
            posted_at_raw=job["postedDate"],
            payload=b"{}",
            fetched_at=datetime.now(UTC),
            content_hash="gh-1",
        ),
        taxonomy=taxonomy,
        geo=geo_index,
        profile=build_profile(_PROFILE_DATA),
        hq_country="US",
    )
    assert ats.outcome == "new"

    run = run_source_cycle(
        store_conn, Source.EFC, [_pseudo_board()], ctx=_ctx(taxonomy, geo_index, registry)
    )

    assert run.status == "ok"
    assert run.fetched == 3
    assert run.aliased == 1  # the fixture's first job is the ATS posting above
    assert run.new == 2
    canonicals = store_conn.execute(
        "SELECT source, company_slug FROM postings WHERE is_canonical = 1 ORDER BY source"
    ).fetchall()
    assert len(canonicals) == 3  # 1 ATS + 2 aggregator-only, NOT 4
    assert {c["company_slug"] for c in canonicals} == {"oxfordknight"}  # resolver, not slugify
    assert list_discovered(store_conn) == []  # a registry employer is never "discovered"


def test_an_aggregator_only_employer_lands_in_the_discovery_report(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex
) -> None:
    registry = [make_board()]  # acme: nothing to do with Oxford Knight
    sync_companies(store_conn, registry)
    store_conn.commit()

    run_source_cycle(
        store_conn, Source.EFC, [_pseudo_board()], ctx=_ctx(taxonomy, geo_index, registry)
    )

    assert list_discovered(store_conn) == [("oxford_knight", "Oxford Knight", 3)]
