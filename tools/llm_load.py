#!/usr/bin/env python3
"""The daily LLM funnel, from real data — blueprint/wp/WP12-match-llm.md §2.

Recomputes how many postings a day actually reach the LLM once the free
stages have run: the content-hash cache, the coarse title/seniority hard
rejects, and finally `match.prefilter.is_ambiguous`. From that residual
count it derives a rough GPU-seconds-per-day estimate.

The hypotheses hardcoded below are the ones the funnel started from before
any real collection ran (see the table in the blueprint). Once
`jobtracker.db` has a few weeks of history, this tool's own output replaces
them as the reference — that is the whole point of it existing as a
standalone, rerunnable script instead of a one-off spreadsheet.

Usage:
    uv run python tools/llm_load.py [--db jobtracker.db] [--days 1]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jobtracker.collect.registry import load_registry
from jobtracker.core.db import connect
from jobtracker.core.models import Compensation, Location, MatchVerdict, Posting
from jobtracker.match.prefilter import is_ambiguous
from jobtracker.match.profile import Profile, load_profile

REPO_ROOT = Path(__file__).resolve().parent.parent

# ~1500 input + ~100 output tokens per posting, batches of 4, on the served
# ~30B-A3B MoE model (§2). `--tokens-per-second` overrides this placeholder
# once a real measurement against the served model exists.
_TOKENS_PER_POSTING = 1500 + 100
_DEFAULT_TOKENS_PER_SECOND = 40.0

_REJECTS_NOT_QUANT = ("not_quant", "excluded_title")
_REJECTS_SENIORITY = ("senior_only", "phd_required")


@dataclass(frozen=True)
class FunnelStage:
    label: str
    count: int
    note: str = ""


# blueprint/wp/WP12-match-llm.md §2 — the starting hypotheses, to be replaced
# by this tool's own real-data output after a few weeks of collection.
def _hypothesis_funnel() -> list[FunnelStage]:
    return [
        FunnelStage("new postings fetched", 300),
        FunnelStage("after content-hash cache", 300, "unchanged postings don't repass"),
        FunnelStage("after not_quant / excluded_title", 90),
        FunnelStage("after senior_only / phd_required", 40),
        FunnelStage("after full deterministic resolution", 12, "the ambiguous residual"),
        FunnelStage("after the prefilter", 8, "what the LLM sees"),
    ]


def _cutoff(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _load_profile() -> Profile:
    boards = load_registry(REPO_ROOT / "configs" / "companies.yaml")
    company_tiers = {b.company_slug: b.priority for b in boards}
    return load_profile(REPO_ROOT / "configs" / "profile.yaml", company_tiers=company_tiers)


def _locations_for(conn: sqlite3.Connection, posting_id: str) -> tuple[Location, ...]:
    rows = conn.execute(
        "SELECT city, country, region, remote_mode, raw FROM posting_locations "
        "WHERE posting_id = ?",
        (posting_id,),
    ).fetchall()
    return tuple(
        Location(
            city=row["city"],
            country=row["country"],
            region=row["region"],
            remote_mode=row["remote_mode"],
            raw=row["raw"],
        )
        for row in rows
    )


def _description_for(conn: sqlite3.Connection, posting_id: str) -> str:
    row = conn.execute(
        "SELECT description FROM posting_search_text WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    return row["description"] if row is not None else ""


def _posting_from_row(row: sqlite3.Row, *, locations: tuple[Location, ...]) -> Posting:
    """Just enough of `Posting` for `is_ambiguous` — every other field is
    filler this tool never reads back (tech, salary amounts, dedup keys, ...).
    """
    return Posting(
        posting_id=row["posting_id"],
        fingerprint=row["fingerprint"],
        source=row["source"],
        company_slug=row["company_slug"],
        source_job_id="",
        url=row["url"],
        title=row["title"],
        title_raw=row["title_raw"],
        role_family=row["role_family"],
        seniority=row["seniority"],
        min_years=row["min_years"],
        phd_required=bool(row["phd_required"]),
        locations=locations,
        compensation=Compensation(
            amount_min=None,
            amount_max=None,
            currency=None,
            period=None,
            bonus_mentioned=False,
            equity_mentioned=False,
            raw=None,
        ),
        visa_sponsorship=row["visa_sponsorship"],
        visa_evidence=row["visa_evidence"],
        tech=frozenset(),
        languages_required=frozenset(),
        posted_at=row["posted_at"],
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        closes_at=row["closes_at"],
        content_hash=row["content_hash"],
        resolver_stage="rules",
        normalize_version=row["normalize_version"],
    )


def _verdict_from_row(row: sqlite3.Row, *, profile_version: int) -> MatchVerdict:
    return MatchVerdict(
        posting_id=row["posting_id"],
        score=row["score"] or 0,
        tier=row["tier"],
        reasons=(),
        rejection_reason=row["rejection_reason"],
        profile_version=profile_version,
        scored_at=datetime.now(UTC),
    )


def compute_funnel(conn: sqlite3.Connection, *, days: int, profile: Profile) -> list[FunnelStage]:
    cutoff = _cutoff(days)

    run_totals = conn.execute(
        "SELECT COALESCE(SUM(fetched), 0) AS fetched, COALESCE(SUM(new + updated), 0) AS changed "
        "FROM source_runs WHERE started_at >= ?",
        (cutoff,),
    ).fetchone()

    rows = conn.execute(
        "SELECT p.*, v.rejection_reason AS rejection_reason "
        "FROM postings p LEFT JOIN verdicts v ON v.posting_id = p.posting_id "
        "WHERE p.first_seen_at >= ?",
        (cutoff,),
    ).fetchall()

    # This mirrors the funnel's own strictly-decreasing waterfall shape rather
    # than `is_ambiguous`'s exact logic: a not_quant rejection at a rank-1
    # company is, in reality, still eligible for the prefilter (§3), but
    # folding that back in here would turn a five-line sanity report into a
    # second implementation of `is_ambiguous` to keep in sync. Good enough for
    # a load estimate; not a substitute for the prefilter's own tests.
    after_title = [r for r in rows if r["rejection_reason"] not in _REJECTS_NOT_QUANT]
    after_seniority = [r for r in after_title if r["rejection_reason"] not in _REJECTS_SENIORITY]
    resolved_or_open = [r for r in after_seniority if r["tier"] != "rejected"]

    reached_prefilter = 0
    for row in resolved_or_open:
        posting = _posting_from_row(row, locations=_locations_for(conn, row["posting_id"]))
        verdict = _verdict_from_row(row, profile_version=profile.version)
        description = _description_for(conn, row["posting_id"])
        if is_ambiguous(posting, verdict, profile=profile, description=description):
            reached_prefilter += 1

    return [
        FunnelStage("new postings fetched", run_totals["fetched"]),
        FunnelStage(
            "after content-hash cache", run_totals["changed"], "unchanged postings don't repass"
        ),
        FunnelStage("after not_quant / excluded_title", len(after_title)),
        FunnelStage("after senior_only / phd_required", len(after_seniority)),
        FunnelStage(
            "after full deterministic resolution", len(resolved_or_open), "the ambiguous residual"
        ),
        FunnelStage("after the prefilter", reached_prefilter, "what the LLM sees"),
    ]


def _print_table(stages: Sequence[FunnelStage]) -> None:
    width = max(len(stage.label) for stage in stages)
    for stage in stages:
        suffix = f"  ({stage.note})" if stage.note else ""
        print(f"  {stage.label.ljust(width)}  {stage.count:>6}{suffix}")


def _gpu_seconds_per_day(to_llm_count: int, *, tokens_per_second: float) -> float:
    return (to_llm_count * _TOKENS_PER_POSTING) / tokens_per_second


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "jobtracker.db")
    parser.add_argument("--days", type=int, default=1, help="lookback window in days")
    parser.add_argument("--tokens-per-second", type=float, default=_DEFAULT_TOKENS_PER_SECOND)
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"{args.db} not found — printing the starting hypotheses instead:\n", file=sys.stderr)
        hypothesis = _hypothesis_funnel()
        _print_table(hypothesis)
        gpu_seconds = _gpu_seconds_per_day(
            hypothesis[-1].count, tokens_per_second=args.tokens_per_second
        )
        print(f"\nestimated GPU load: {gpu_seconds:.1f}s/day (hypothetical)")
        return 0

    profile = _load_profile()
    conn = connect(args.db)
    try:
        stages = compute_funnel(conn, days=args.days, profile=profile)
    finally:
        conn.close()

    print(f"funnel over the last {args.days} day(s):\n")
    _print_table(stages)
    to_llm = stages[-1].count
    gpu_seconds = _gpu_seconds_per_day(to_llm, tokens_per_second=args.tokens_per_second)
    print(f"\nestimated GPU load: {gpu_seconds:.1f}s/day, at {args.tokens_per_second:.0f} tok/s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
