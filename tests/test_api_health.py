"""`/health` contract tests — blueprint/07-ERRORS-AND-LOGGING.md §5."""

import sqlite3
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from factories_store import make_board
from jobtracker.core.enums import Source
from jobtracker.core.models import SourceRun
from jobtracker.store.companies import sync_companies
from jobtracker.store.runs import record_run

pytestmark = pytest.mark.db


def test_health_on_a_fresh_install_is_200(api_client: TestClient) -> None:
    resp = api_client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["feed"]["stale"] is False
    assert body["alerts"] == []


def test_health_is_200_even_when_degraded(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    sync_companies(api_conn, [make_board(source=Source.GREENHOUSE, enabled=True)])
    for i in range(3):
        record_run(
            api_conn,
            SourceRun(
                run_id=f"r{i}",
                source=Source.GREENHOUSE,
                company_slug=None,
                started_at=datetime(2026, 3, 1 + i, tzinfo=UTC),
                ended_at=datetime(2026, 3, 1 + i, tzinfo=UTC),
                fetched=0,
                new=0,
                updated=0,
                aliased=0,
                rejected=0,
                requests_made=1,
                status="empty",
                error_kind=None,
            ),
        )
    api_conn.commit()

    resp = api_client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["sources"][0]["status"] == "degraded"
    assert body["alerts"][0]["kind"] == "source_mute"
