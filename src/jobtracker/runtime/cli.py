"""`jobtracker` — the command-line entry point — blueprint/wp/WP08-runtime.md §6."""

import argparse
import json
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from ulid import ULID

from jobtracker.collect.http import PolicedHttpSession, load_sources_config
from jobtracker.collect.registry import boards_for_source, load_registry
from jobtracker.core.clock import utc_now
from jobtracker.core.config import Settings, load_settings
from jobtracker.core.db import apply_migrations, connect
from jobtracker.core.enums import Source
from jobtracker.core.geo import load_geo_index
from jobtracker.core.logging import bound_run_id, configure_logging, get_logger
from jobtracker.core.models import Board
from jobtracker.match.profile import load_profile
from jobtracker.normalize.taxonomy import load_taxonomy
from jobtracker.runtime.aggregator_loader import load_aggregators
from jobtracker.runtime.pipeline import ingest
from jobtracker.runtime.replay import UnknownStage, format_report, run_replay
from jobtracker.runtime.report import build_weekly_report
from jobtracker.runtime.residual import DRAIN_INTERVAL_MIN, LlmClientConfig, drain_queue
from jobtracker.runtime.scheduler import CycleContext, run_source_cycle
from jobtracker.runtime.watchdog import full_health_snapshot
from jobtracker.store.backup import DEFAULT_KEEP_DAYS, backup_database
from jobtracker.store.companies import list_discovered, sync_companies
from jobtracker.store.retention import run_retention
from jobtracker.store.schema import MIGRATIONS_DIR

_logger = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIGS_DIR = REPO_ROOT / "configs"
_LOOP_POLL_S = 5.0
_RETENTION_INTERVAL_S = 24 * 3600.0


def _connect_and_migrate(settings: Settings) -> sqlite3.Connection:
    conn = connect(settings.db_path)
    apply_migrations(conn, MIGRATIONS_DIR)
    return conn


def _build_context(
    conn: sqlite3.Connection, settings: Settings
) -> tuple[CycleContext, list[Board]]:
    boards = load_registry(CONFIGS_DIR / "companies.yaml")
    sync_companies(conn, boards)
    conn.commit()
    taxonomy = load_taxonomy(CONFIGS_DIR / "taxonomy.yaml")
    geo = load_geo_index(CONFIGS_DIR / "geo.yaml")
    company_tiers = {b.company_slug: b.priority for b in boards}
    profile = load_profile(CONFIGS_DIR / "profile.yaml", company_tiers=company_tiers)
    sources_config = load_sources_config(CONFIGS_DIR / "sources.yaml")
    ctx = CycleContext(
        sources_config=sources_config,
        taxonomy=taxonomy,
        geo=geo,
        profile=profile,
        user_agent=settings.user_agent,
        llm=LlmClientConfig.from_settings(settings),
    )
    aggregators = load_aggregators(settings, boards, configs_dir=CONFIGS_DIR)
    if aggregators is not None:
        ctx.collectors.update(aggregators.collectors)
        ctx.client_factories = aggregators.client_factories
        ctx.resolve_employer = aggregators.resolve_employer
        boards = [*boards, *aggregators.boards]
    return ctx, boards


def cmd_migrate(_args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    conn.close()
    print("migrations applied", file=sys.stderr)
    return 0


def cmd_run_once(args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, boards = _build_context(conn, settings)
    source = Source(args.source)
    source_boards = boards_for_source(boards, source)
    if args.company:
        source_boards = [b for b in source_boards if b.company_slug == args.company]

    with bound_run_id(str(ULID())):
        run = run_source_cycle(conn, source, source_boards, ctx=ctx)
    print(
        f"source={run.source.value} status={run.status} fetched={run.fetched} "
        f"new={run.new} updated={run.updated} aliased={run.aliased} rejected={run.rejected} "
        f"requests_made={run.requests_made}",
        file=sys.stderr,
    )
    conn.close()
    return 0


def cmd_loop(_args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, boards = _build_context(conn, settings)
    sources = sorted({b.source for b in boards}, key=lambda s: s.value)
    next_due: dict[Source, float] = dict.fromkeys(sources, 0.0)
    next_drain = 0.0
    next_retention = 0.0

    _logger.info("loop_started", sources=[s.value for s in sources])
    try:
        while True:
            now_monotonic = time.monotonic()
            for source in sources:
                if not ctx.sources_config.is_enabled(source):
                    continue
                if next_due[source] > now_monotonic:
                    continue
                source_boards = boards_for_source(boards, source)
                if not source_boards:
                    continue
                with bound_run_id(str(ULID())):
                    run_source_cycle(conn, source, source_boards, ctx=ctx)
                interval_min = ctx.sources_config.interval_min.get(str(source), 180)
                next_due[source] = now_monotonic + interval_min * 60
            if ctx.llm is not None and next_drain <= now_monotonic:
                with bound_run_id(str(ULID())):
                    drain_queue(conn, profile=ctx.profile, cfg=ctx.llm)
                next_drain = time.monotonic() + DRAIN_INTERVAL_MIN * 60
            if next_retention <= now_monotonic:
                run_retention(conn, now=utc_now())
                next_retention = time.monotonic() + _RETENTION_INTERVAL_S
            time.sleep(_LOOP_POLL_S)
    except KeyboardInterrupt:
        _logger.info("loop_stopped")
        return 0
    finally:
        conn.close()


def cmd_llm_drain(_args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, _boards = _build_context(conn, settings)
    if ctx.llm is None:
        print("JT_LLM_ENABLED=false: nothing to drain", file=sys.stderr)
        conn.close()
        return 0
    with bound_run_id(str(ULID())):
        result = drain_queue(conn, profile=ctx.profile, cfg=ctx.llm)
    print(
        f"resolved={result.resolved} quarantined={result.quarantined} dropped={result.dropped} "
        f"requeued={result.requeued} remaining={result.remaining} "
        f"server_available={result.server_available}",
        file=sys.stderr,
    )
    conn.close()
    return 0


def cmd_discover_employers(_args: argparse.Namespace) -> int:
    """Employers seen at an aggregator and absent from `companies.yaml` — WP13 §4.

    The durable contribution of a fragile source: each line is a candidate for
    `tools/probe_ats.py` and the registry (WP00), sorted by how many postings the
    aggregators showed for it.
    """
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    discovered = list_discovered(conn)
    conn.close()
    if not discovered:
        print("no employers discovered through aggregators yet", file=sys.stderr)
        return 0
    print(f"{'postings':>8}  {'slug':<32} name")
    for slug, name, postings in discovered:
        print(f"{postings:>8}  {slug:<32} {name}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, _boards = _build_context(conn, settings)
    since = datetime.fromisoformat(args.since).replace(tzinfo=UTC) if args.since else None
    try:
        report = run_replay(
            conn,
            taxonomy=ctx.taxonomy,
            geo=ctx.geo,
            profile=ctx.profile,
            stage=args.stage,
            since=since,
            normalize_version_below=args.normalize_version_below,
            apply=args.apply,
            allow_regression=args.allow_regression,
        )
    except UnknownStage as exc:
        print(str(exc), file=sys.stderr)
        conn.close()
        return 2
    conn.close()
    print(format_report(report))
    # A regression is the whole point of the tool: it must not pass silently in a script.
    return 1 if report.regressions or report.refused else 0


def cmd_report(args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, _boards = _build_context(conn, settings)
    now = utc_now()
    markdown = build_weekly_report(conn, ctx.sources_config, ctx.profile, now=now)
    conn.close()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{now.date()}-weekly.md"
    path.write_text(markdown, encoding="utf-8")
    print(f"wrote {path}", file=sys.stderr)
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    path = backup_database(conn, Path(args.dest), now=utc_now(), keep_days=args.keep_days)
    conn.close()
    print(f"backup written: {path}", file=sys.stderr)
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    sources_config = load_sources_config(CONFIGS_DIR / "sources.yaml")
    snapshot = full_health_snapshot(conn, sources_config)
    conn.close()

    print(json.dumps(snapshot.model_dump(mode="json"), indent=2))
    degraded = snapshot.feed.stale or any(s.status == "degraded" for s in snapshot.sources)
    return 1 if degraded else 0


def cmd_probe(args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, boards = _build_context(conn, settings)
    board = next((b for b in boards if b.company_slug == args.company), None)
    if board is None:
        print(f"no such company in the registry: {args.company!r}", file=sys.stderr)
        conn.close()
        return 1

    collector = ctx.collectors[board.source]
    session = PolicedHttpSession(
        client=httpx.Client(),
        config=ctx.sources_config.for_source(board.source),
        user_agent=ctx.user_agent,
    )
    with bound_run_id(str(ULID())):
        result = collector.fetch(board, session)
        print(
            f"requests_made={result.requests_made} truncated={result.truncated} "
            f"postings={len(result.postings)}",
            file=sys.stderr,
        )
        for raw in result.postings:
            outcome = ingest(
                conn,
                raw,
                taxonomy=ctx.taxonomy,
                geo=ctx.geo,
                profile=ctx.profile,
                hq_country=board.hq_country,
                llm=ctx.llm,
            )
            print(
                f"  {raw.title_raw!r} -> {outcome.outcome} "
                f"(posting_id={outcome.posting_id}, tier={outcome.tier})",
                file=sys.stderr,
            )
    conn.close()
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobtracker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("migrate", help="apply pending migrations").set_defaults(func=cmd_migrate)

    run_once = subparsers.add_parser("run-once", help="one collection cycle on a single source")
    run_once.add_argument("--source", required=True, choices=[s.value for s in Source])
    run_once.add_argument("--company", default=None)
    run_once.set_defaults(func=cmd_run_once)

    subparsers.add_parser("loop", help="run continuously").set_defaults(func=cmd_loop)

    subparsers.add_parser("llm-drain", help="one pass over the deferred LLM queue").set_defaults(
        func=cmd_llm_drain
    )

    subparsers.add_parser(
        "discover-employers", help="employers seen only at aggregators, for the registry"
    ).set_defaults(func=cmd_discover_employers)

    replay = subparsers.add_parser("replay", help="replay the normalizer on archived inputs")
    replay.add_argument("--since", default=None, help="ISO date: only postings first seen since")
    replay.add_argument("--stage", default=None, help="one stage only (seniority, visa, ...)")
    replay.add_argument("--normalize-version-below", type=int, default=None)
    replay.add_argument("--dry-run", action="store_true", help="the default; accepted for clarity")
    replay.add_argument("--apply", action="store_true", help="write the result (never the default)")
    replay.add_argument("--allow-regression", action="store_true")
    replay.set_defaults(func=cmd_replay)

    report = subparsers.add_parser("report", help="the weekly markdown report")
    report.add_argument("--weekly", action="store_true", required=True)
    report.add_argument("--out-dir", default=str(REPO_ROOT / "docs" / "reports"))
    report.set_defaults(func=cmd_report)

    backup = subparsers.add_parser("backup", help="online SQLite backup, integrity-checked")
    backup.add_argument("--dest", required=True, help="directory to write the backup into")
    backup.add_argument("--keep-days", type=int, default=DEFAULT_KEEP_DAYS)
    backup.set_defaults(func=cmd_backup)

    status = subparsers.add_parser("status", help="health snapshot; exit 1 if degraded")
    status.set_defaults(func=cmd_status)

    probe = subparsers.add_parser("probe", help="fetch one company, verbosely, for debugging")
    probe.add_argument("--company", required=True)
    probe.set_defaults(func=cmd_probe)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
