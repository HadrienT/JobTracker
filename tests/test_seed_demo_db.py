"""The e2e demo database must be reproducible — blueprint/wp/WP14-quality.md §2.3.

A browser assertion such as "the first row after sorting by date" only means something if
the database behind it is the same on every run. Posting ids are random ULIDs, so this
compares everything that is *content*: title, score, tier and the frozen timestamps.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parent.parent


def _seed(target: Path) -> list[tuple]:
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "seed_demo_db.py"), str(target)],
        check=True,
        capture_output=True,
    )
    conn = sqlite3.connect(target)
    try:
        return conn.execute(
            "SELECT title, score, tier, first_seen_at, company_slug FROM postings "
            "ORDER BY title, first_seen_at"
        ).fetchall()
    finally:
        conn.close()


def test_the_demo_database_is_identical_from_one_run_to_the_next(tmp_path: Path) -> None:
    first = _seed(tmp_path / "a.db")
    second = _seed(tmp_path / "b.db")
    assert first, "the demo database has no postings"
    assert first == second


def test_the_demo_database_covers_what_the_journey_filters_on(tmp_path: Path) -> None:
    _seed(tmp_path / "demo.db")
    conn = sqlite3.connect(tmp_path / "demo.db")
    try:
        us_python = conn.execute(
            "SELECT COUNT(DISTINCT p.posting_id) FROM postings p "
            "JOIN posting_locations l ON l.posting_id = p.posting_id "
            "JOIN posting_tech t ON t.posting_id = p.posting_id "
            "WHERE l.country = 'US' AND t.tech = 'python' AND p.tier != 'rejected'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert us_python > 0
