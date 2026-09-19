"""`/export/postings.csv` — the feed as a file."""

import csv
import io
import sqlite3

import pytest
from fastapi.testclient import TestClient

from factories_store import make_board, make_posting, make_verdict
from jobtracker.core.enums import Tier
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import upsert_posting

pytestmark = pytest.mark.db


def _seed(conn: sqlite3.Connection, n: int) -> None:
    sync_companies(conn, [make_board()])
    for i in range(n):
        posting_id = f"p-{i:04d}"
        posting = make_posting(
            posting_id=posting_id,
            source_job_id=posting_id,
            fingerprint=f"fp-{i}",
            title=f'Quant "Dev", desk {i}',  # quotes and a comma: the CSV must survive them
        )
        upsert_posting(conn, posting, make_verdict(posting_id=posting_id, score=100 - i % 90))
    conn.commit()


def _parse(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_the_export_is_a_csv_attachment(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    _seed(api_conn, 3)

    response = api_client.get("/export/postings.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]


def test_every_posting_is_there_across_pages(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    _seed(api_conn, 250)  # more than two pages of 100

    rows = _parse(api_client.get("/export/postings.csv").text)

    assert len(rows) == 250
    assert len({r["url"] + r["title"] for r in rows}) == 250  # no page repeated, none skipped


def test_quotes_and_commas_in_a_title_round_trip(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    _seed(api_conn, 1)

    (row,) = _parse(api_client.get("/export/postings.csv").text)

    assert row["title"] == 'Quant "Dev", desk 0'
    assert row["company"] and row["url"]


def test_the_export_honours_the_feed_filters_and_the_sort(
    api_client: TestClient, api_conn: sqlite3.Connection
) -> None:
    _seed(api_conn, 5)
    api_conn.execute(
        "UPDATE postings SET tier = ? WHERE posting_id = 'p-0000'", (Tier.STRETCH.value,)
    )
    api_conn.commit()

    only_stretch = _parse(api_client.get("/export/postings.csv?tiers=stretch").text)
    by_score = [int(r["score"]) for r in _parse(api_client.get("/export/postings.csv").text)]

    assert len(only_stretch) == 1
    assert by_score == sorted(by_score, reverse=True)


def test_an_empty_feed_is_just_the_header(api_client: TestClient) -> None:
    text = api_client.get("/export/postings.csv").text

    assert text.splitlines() == [
        "score,tier,title,company,sector,locations,remote,seniority,min_years,visa,tech,"
        "salary,posted_at,first_seen_at,closes_at,application_status,url"
    ]
