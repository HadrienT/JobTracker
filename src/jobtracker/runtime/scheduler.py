"""One source's collection cycle — blueprint/05-SEQUENCES.md §1, blueprint/wp/WP08-runtime.md §3.

Cadence has two independent layers: `configs/sources.yaml`'s `interval_min`
decides how often the *source* itself is even looked at (the caller's job —
see `cli.py`), while a board's registry `priority` decides how often *that
company* is actually fetched once its source is due (this module's job:
priority 1 every cycle, 2 daily, 3 weekly). Board order is reshuffled every
cycle so a fixed alphabetical order never lets late-alphabet companies be
the ones that silently starve when a request budget runs out.
"""

import random
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx
from ulid import ULID

from jobtracker.collect.ats.ashby import AshbyCollector
from jobtracker.collect.ats.greenhouse import GreenhouseCollector
from jobtracker.collect.ats.lever import LeverCollector
from jobtracker.collect.ats.personio import PersonioCollector
from jobtracker.collect.ats.recruitee import RecruiteeCollector
from jobtracker.collect.ats.smartrecruiters import SmartRecruitersCollector
from jobtracker.collect.ats.workable import WorkableCollector
from jobtracker.collect.ats.workday import WorkdayCollector
from jobtracker.collect.base import Collector
from jobtracker.collect.custom import CustomCollector
from jobtracker.collect.http import PolicedHttpSession, SourcesConfig
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Source, Tier
from jobtracker.core.errors import BoardNotFound, CollectError, SourceBlocked, SourceUnavailable
from jobtracker.core.geo import GeoIndex
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board, SourceRun
from jobtracker.match.profile import Profile
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.runtime.breaker import BreakerStatus, compute_state
from jobtracker.runtime.pipeline import ingest
from jobtracker.store.postings import deactivate_missing
from jobtracker.store.runs import last_run_at_for_board, recent_runs, record_run

_logger = get_logger(__name__)

DEFAULT_COLLECTORS: dict[Source, Collector] = {
    Source.GREENHOUSE: GreenhouseCollector(),
    Source.LEVER: LeverCollector(),
    Source.ASHBY: AshbyCollector(),
    Source.SMARTRECRUITERS: SmartRecruitersCollector(),
    Source.WORKABLE: WorkableCollector(),
    Source.RECRUITEE: RecruiteeCollector(),
    Source.PERSONIO: PersonioCollector(),
    Source.WORKDAY: WorkdayCollector(),
    Source.CUSTOM: CustomCollector(),
}

_PRIORITY_INTERVALS = {2: timedelta(days=1), 3: timedelta(days=7)}
_BREAKER_HISTORY_DEPTH = 50


@dataclass
class _Stats:
    fetched: int = 0
    new: int = 0
    updated: int = 0
    aliased: int = 0
    rejected: int = 0

    def add(self, other: "_Stats") -> None:
        self.fetched += other.fetched
        self.new += other.new
        self.updated += other.updated
        self.aliased += other.aliased
        self.rejected += other.rejected


@dataclass
class CycleContext:
    """Everything one source's cycle needs, gathered once by the caller."""

    sources_config: SourcesConfig
    taxonomy: Taxonomy
    geo: GeoIndex
    profile: Profile
    user_agent: str
    collectors: dict[Source, Collector] = field(default_factory=lambda: dict(DEFAULT_COLLECTORS))


def is_board_due(conn: sqlite3.Connection, board: Board, *, now: datetime) -> bool:
    if board.priority <= 1:
        return True
    last = last_run_at_for_board(conn, board.source, board.company_slug)
    if last is None:
        return True
    return now - last >= _PRIORITY_INTERVALS.get(board.priority, timedelta(0))


def run_source_cycle(
    conn: sqlite3.Connection, source: Source, boards: list[Board], *, ctx: CycleContext
) -> SourceRun:
    """Run one full cycle for `source` over `boards` (already filtered to that source).

    Always writes an aggregate `source_runs` row (company_slug=None) and,
    for every board actually attempted, a per-board row too — `store.health`
    reads the aggregate rows for breaker/watchdog purposes and the per-board
    rows for the boards_ok/boards_error counts.
    """
    now = utc_now()
    run_id = str(ULID())
    breaker = compute_state(
        [
            r
            for r in recent_runs(conn, source, limit=_BREAKER_HISTORY_DEPTH)
            if r.company_slug is None
        ],
        now=now,
    )

    if breaker.status == BreakerStatus.OPEN:
        _logger.info("scheduler_source_skipped", source=source.value, run_id=run_id)
        run = _make_run(run_id, source, None, now, _Stats(), 0, status="skipped", error_kind=None)
        record_run(conn, run)
        conn.commit()
        return run

    due = [b for b in boards if b.enabled and is_board_due(conn, b, now=now)]
    random.shuffle(due)
    if breaker.status == BreakerStatus.HALF_OPEN and due:
        due = [random.choice(due)]

    collector = ctx.collectors[source]
    http_config = ctx.sources_config.for_source(source)
    session = PolicedHttpSession(
        client=httpx.Client(), config=http_config, user_agent=ctx.user_agent
    )

    totals = _Stats()
    requests_made = 0
    blocked = False
    any_attempt_succeeded = False

    for board in due:
        try:
            result = collector.fetch(board, session)
        except SourceBlocked:
            _logger.warning(
                "collect_source_blocked", source=source.value, company_slug=board.company_slug
            )
            record_run(
                conn,
                _make_run(
                    run_id,
                    source,
                    board.company_slug,
                    now,
                    _Stats(),
                    0,
                    status="blocked",
                    error_kind="SourceBlocked",
                ),
            )
            conn.commit()
            blocked = True
            break
        except (SourceUnavailable, BoardNotFound, CollectError) as exc:
            _logger.error(
                "collect_board_failed",
                source=source.value,
                company_slug=board.company_slug,
                error_kind=type(exc).__name__,
            )
            record_run(
                conn,
                _make_run(
                    run_id,
                    source,
                    board.company_slug,
                    now,
                    _Stats(),
                    0,
                    status="error",
                    error_kind=type(exc).__name__,
                ),
            )
            conn.commit()
            continue

        any_attempt_succeeded = True
        requests_made += result.requests_made
        board_stats = _Stats()
        for raw in result.postings:
            outcome = ingest(
                conn,
                raw,
                taxonomy=ctx.taxonomy,
                geo=ctx.geo,
                profile=ctx.profile,
                hq_country=board.hq_country,
            )
            board_stats.fetched += 1
            if outcome.outcome == "new":
                board_stats.new += 1
            elif outcome.outcome == "updated":
                board_stats.updated += 1
            elif outcome.outcome == "aliased":
                board_stats.aliased += 1
            if outcome.tier == Tier.REJECTED:
                board_stats.rejected += 1

        if result.postings:
            # blueprint/05-SEQUENCES.md §4: only a *non-empty* result may
            # deactivate postings absent from it — a zero-offer response
            # never deactivates anything, indistinguishable as it is from a
            # broken token.
            seen_ids = {raw.source_job_id for raw in result.postings}
            deactivate_missing(conn, source, board.company_slug, seen_ids)

        totals.add(board_stats)
        board_status = "ok" if result.postings else "empty"
        record_run(
            conn,
            _make_run(
                run_id,
                source,
                board.company_slug,
                now,
                board_stats,
                result.requests_made,
                status=board_status,
                error_kind=None,
            ),
        )
        conn.commit()

    aggregate_status = _aggregate_status(blocked, any_attempt_succeeded, totals, bool(due))
    aggregate = _make_run(
        run_id, source, None, now, totals, requests_made, status=aggregate_status, error_kind=None
    )
    record_run(conn, aggregate)
    conn.commit()
    return aggregate


def _aggregate_status(
    blocked: bool, any_success: bool, totals: _Stats, had_due_boards: bool
) -> str:
    if blocked:
        return "blocked"
    if not had_due_boards:
        return "empty"
    if not any_success:
        return "error"
    return "ok" if totals.fetched > 0 else "empty"


def _make_run(  # noqa: PLR0917 — one positional per SourceRun field it's assembling
    run_id: str,
    source: Source,
    company_slug: str | None,
    started_at: datetime,
    stats: _Stats,
    requests_made: int,
    *,
    status: str,
    error_kind: str | None,
) -> SourceRun:
    return SourceRun(
        run_id=run_id,
        source=source,
        company_slug=company_slug,
        started_at=started_at,
        ended_at=utc_now(),
        fetched=stats.fetched,
        new=stats.new,
        updated=stats.updated,
        aliased=stats.aliased,
        rejected=stats.rejected,
        requests_made=requests_made,
        status=status,
        error_kind=error_kind,
    )
