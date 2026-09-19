"""`runtime.scheduler.run_source_cycle` contract tests — blueprint/wp/WP08-runtime.md §3, §7."""

import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from factories_store import make_board
from jobtracker.collect.http import HttpSession, build_sources_config
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceBlocked, SourceUnavailable
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import Board, CollectResult, RawPosting, SourceRun
from jobtracker.match.profile import Profile, build_profile
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.runtime import pipeline
from jobtracker.runtime.scheduler import CycleContext, is_board_due, run_source_cycle
from jobtracker.store.companies import sync_companies
from jobtracker.store.runs import record_run

pytestmark = pytest.mark.db

_PROFILE_DATA = {
    "version": 1,
    "titles": {"strong": ["quant developer"], "possible": [], "excluded": []},
    "seniority": {"accept_if_years_max": 3, "reject": []},
    "hard_rejects": {"phd_required": True, "min_years_above": 4, "stale_after_days": 60},
    "weights": {
        "title_strong": 35,
        "title_possible": 18,
        "sector_tier1": 12,
        "tech_cpp": 10,
        "tech_python": 6,
        "tech_niche": 8,
        "seniority_match": 20,
        "graduate_programme": 10,
        "visa_sponsors": 8,
        "visa_no": -25,
        "salary_disclosed": 3,
        "freshness_7d": 6,
        "stale_penalty": -10,
    },
    "tiers": {"strong": 70, "possible": 45, "stretch": 25},
    "freshness": {"window_days": 7, "stale_penalty_fraction": 0.5},
    "llm": {
        "min_description_chars": 200,
        "high_confidence_margin": 20,
        "min_confidence": 0.6,
        "max_description_chars": 6000,
    },
    "review": {
        "version": 1,
        "override_confidence": 0.8,
        "evidence_min_chars": 6,
        "max_locations": 8,
        "max_per_collect": 300,
        "max_output_tokens": 1200,
        "max_description_chars": 12000,
        "salary_bounds": {
            "year": [10000, 10000000],
            "month": [500, 500000],
            "day": [20, 20000],
            "hour": [5, 5000],
        },
        "currencies": ["USD", "EUR", "GBP", "CHF", "SGD", "HKD"],
    },
}


@dataclass
class _FakeCollector:
    source: Source
    postings_by_board: dict[str, tuple[RawPosting, ...]] = field(default_factory=dict)
    raise_by_board: dict[str, Exception] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def fetch(self, board: Board, session: HttpSession) -> CollectResult:
        self.calls.append(board.company_slug)
        if board.company_slug in self.raise_by_board:
            raise self.raise_by_board[board.company_slug]
        postings = self.postings_by_board.get(board.company_slug, ())
        return CollectResult(
            board=board, postings=postings, requests_made=1, duration_ms=0, truncated=False
        )


def _raw(company_slug: str, source_job_id: str, **overrides: object) -> RawPosting:
    base: dict[str, object] = {
        "source": Source.GREENHOUSE,
        "company_slug": company_slug,
        "source_job_id": source_job_id,
        "url": f"https://example.com/{company_slug}/{source_job_id}",
        "title_raw": "Quant Developer",
        "description_raw": "C++ pricing engine.",
        "location_raw": "Paris, France",
        "department_raw": None,
        "posted_at_raw": None,
        "payload": b"{}",
        "fetched_at": datetime(2026, 1, 1, tzinfo=UTC),
        "content_hash": f"hash-{company_slug}-{source_job_id}",
    }
    base.update(overrides)
    return RawPosting(**base)  # type: ignore[arg-type]


def _ctx(
    collector: _FakeCollector, *, taxonomy: Taxonomy, geo: GeoIndex, profile: Profile
) -> CycleContext:
    sources_config = build_sources_config(
        {"defaults": {"jitter_s": [0, 0]}, "sources": {"greenhouse": {"enabled": True}}}
    )
    return CycleContext(
        sources_config=sources_config,
        taxonomy=taxonomy,
        geo=geo,
        profile=profile,
        user_agent="JobTracker-Test/1.0",
        collectors={Source.GREENHOUSE: collector},
    )


@pytest.fixture
def profile() -> Profile:
    return build_profile(_PROFILE_DATA)


@pytest.fixture(autouse=True)
def _companies(store_conn: sqlite3.Connection) -> None:
    sync_companies(
        store_conn,
        [
            make_board(company_slug="acme", priority=1),
            make_board(company_slug="beta", priority=1),
        ],
    )
    store_conn.commit()


def _boards() -> list[Board]:
    return [
        make_board(company_slug="acme", priority=1),
        make_board(company_slug="beta", priority=1),
    ]


def test_a_full_cycle_normalizes_scores_and_stores(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    collector = _FakeCollector(
        source=Source.GREENHOUSE,
        postings_by_board={"acme": (_raw("acme", "1"),), "beta": (_raw("beta", "1"),)},
    )
    ctx = _ctx(collector, taxonomy=taxonomy, geo=geo_index, profile=profile)

    run = run_source_cycle(store_conn, Source.GREENHOUSE, _boards(), ctx=ctx)

    assert run.status == "ok"
    assert run.fetched == 2
    assert run.new == 2
    titles = [r["title"] for r in store_conn.execute("SELECT title FROM postings").fetchall()]
    assert titles == ["Quant Developer", "Quant Developer"]


def test_a_board_error_does_not_stop_the_next_board(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    collector = _FakeCollector(
        source=Source.GREENHOUSE,
        postings_by_board={"beta": (_raw("beta", "1"),)},
        raise_by_board={"acme": SourceUnavailable("timeout")},
    )
    ctx = _ctx(collector, taxonomy=taxonomy, geo=geo_index, profile=profile)

    run = run_source_cycle(store_conn, Source.GREENHOUSE, _boards(), ctx=ctx)

    assert sorted(collector.calls) == ["acme", "beta"]  # both boards were attempted
    assert run.new == 1
    error_rows = store_conn.execute(
        "SELECT company_slug, status, error_kind FROM source_runs WHERE status = 'error'"
    ).fetchall()
    assert [r["company_slug"] for r in error_rows] == ["acme"]
    assert error_rows[0]["error_kind"] == "SourceUnavailable"


def test_source_blocked_stops_remaining_boards_this_cycle(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    collector = _FakeCollector(
        source=Source.GREENHOUSE, raise_by_board={"acme": SourceBlocked("403")}
    )
    ctx = _ctx(collector, taxonomy=taxonomy, geo=geo_index, profile=profile)
    boards = [b for b in _boards() if b.company_slug == "acme"] + [
        b for b in _boards() if b.company_slug == "beta"
    ]

    run = run_source_cycle(store_conn, Source.GREENHOUSE, boards, ctx=ctx)

    assert run.status == "blocked"


def test_a_normalizer_crash_on_one_posting_does_not_lose_the_run(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_normalize = pipeline.normalize
    calls = {"n": 0}

    def _flaky(raw: RawPosting, **kwargs: object) -> object:
        calls["n"] += 1
        if raw.source_job_id == "boom":
            raise ValueError("exotic posting")
        return real_normalize(raw, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pipeline, "normalize", _flaky)

    collector = _FakeCollector(
        source=Source.GREENHOUSE,
        postings_by_board={"acme": (_raw("acme", "boom"), _raw("acme", "fine"))},
    )
    ctx = _ctx(collector, taxonomy=taxonomy, geo=geo_index, profile=profile)

    run = run_source_cycle(store_conn, Source.GREENHOUSE, _boards(), ctx=ctx)

    assert calls["n"] == 2  # both postings were attempted despite the crash
    assert run.fetched == 2
    assert run.new == 1  # only the survivor made it into postings
    assert (
        store_conn.execute("SELECT COUNT(*) c FROM raw_payloads").fetchone()["c"] == 2
    )  # both payloads archived regardless


def test_a_zero_posting_run_deactivates_nothing(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    collector = _FakeCollector(
        source=Source.GREENHOUSE, postings_by_board={"acme": (_raw("acme", "1"),)}
    )
    ctx = _ctx(collector, taxonomy=taxonomy, geo=geo_index, profile=profile)
    run_source_cycle(store_conn, Source.GREENHOUSE, [_boards()[0]], ctx=ctx)

    # Second cycle: the board now (falsely) reports nothing at all.
    collector.postings_by_board = {}
    run = run_source_cycle(store_conn, Source.GREENHOUSE, [_boards()[0]], ctx=ctx)

    assert run.status == "empty"
    row = store_conn.execute("SELECT is_active FROM postings").fetchone()
    assert row["is_active"] == 1  # still active — a zero-run never deactivates


def test_boards_are_shuffled_across_cycles(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    many_boards = [make_board(company_slug=f"c{i}", priority=1) for i in range(20)]
    orders = set()
    for _ in range(5):
        collector = _FakeCollector(source=Source.GREENHOUSE)
        ctx = _ctx(collector, taxonomy=taxonomy, geo=geo_index, profile=profile)
        run_source_cycle(store_conn, Source.GREENHOUSE, many_boards, ctx=ctx)
        orders.add(tuple(collector.calls))
    assert len(orders) > 1  # vanishingly unlikely to collide 5 times by chance


def test_priority_1_board_is_always_due(store_conn: sqlite3.Connection) -> None:
    board = make_board(company_slug="acme", priority=1)
    assert is_board_due(store_conn, board, now=datetime(2026, 1, 1, tzinfo=UTC)) is True


def test_priority_3_board_is_not_due_right_after_being_run(
    store_conn: sqlite3.Connection,
) -> None:
    board = make_board(company_slug="acme", priority=3, source=Source.GREENHOUSE)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    record_run(store_conn, _run_row(now))
    store_conn.commit()
    assert is_board_due(store_conn, board, now=now + timedelta(hours=1)) is False
    assert is_board_due(store_conn, board, now=now + timedelta(days=8)) is True


def test_force_refetches_a_board_that_is_not_due(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    board = make_board(company_slug="acme", priority=3, source=Source.GREENHOUSE)
    collector = _FakeCollector(
        source=Source.GREENHOUSE, postings_by_board={"acme": (_raw("acme", "1"),)}
    )
    ctx = _ctx(collector, taxonomy=taxonomy, geo=geo_index, profile=profile)
    record_run(store_conn, _run_row(utc_now()))  # fetched a moment ago: not due
    store_conn.commit()

    skipped = run_source_cycle(store_conn, Source.GREENHOUSE, [board], ctx=ctx)
    forced = run_source_cycle(store_conn, Source.GREENHOUSE, [board], ctx=ctx, force=True)

    assert skipped.fetched == 0
    assert forced.fetched == 1


def _run_row(started_at: datetime) -> SourceRun:
    return SourceRun(
        run_id="r1",
        source=Source.GREENHOUSE,
        company_slug="acme",
        started_at=started_at,
        ended_at=started_at,
        fetched=0,
        new=0,
        updated=0,
        aliased=0,
        rejected=0,
        requests_made=1,
        status="empty",
        error_kind=None,
    )
