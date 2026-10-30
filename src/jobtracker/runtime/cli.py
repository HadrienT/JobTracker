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

from jobtracker.career.dossier import scan_dossier
from jobtracker.career.sheet import parse_sheet
from jobtracker.collect.browser import BrowserClient
from jobtracker.collect.http import PolicedHttpSession, load_sources_config
from jobtracker.collect.registry import boards_for_source, load_registry
from jobtracker.core.clock import utc_now
from jobtracker.core.config import Settings, load_settings, load_yaml
from jobtracker.core.db import apply_migrations, connect
from jobtracker.core.enums import Source
from jobtracker.core.geo import load_geo_index
from jobtracker.core.logging import bound_run_id, configure_logging, get_logger
from jobtracker.core.models import Board
from jobtracker.match.profile import load_profile, load_tracks
from jobtracker.normalize.taxonomy import load_taxonomy
from jobtracker.runtime.aggregator_loader import load_aggregators
from jobtracker.runtime.app_cli import add_app_parser
from jobtracker.runtime.applications import import_history, report_lines
from jobtracker.runtime.pipeline import ingest
from jobtracker.runtime.replay import UnknownStage, format_report, run_replay
from jobtracker.runtime.report import build_weekly_report
from jobtracker.runtime.residual import (
    DRAIN_INTERVAL_MIN,
    LlmClientConfig,
    drain_all,
    drain_queue,
    enqueue_backlog,
)
from jobtracker.runtime.review import (
    REVERTIBLE_FIELDS,
    ReviewStats,
    ReviewStep,
    revert_corrections,
    review_all,
)
from jobtracker.runtime.scheduler import CycleContext, run_source_cycle
from jobtracker.runtime.tracks import TrackPass, score_tracks
from jobtracker.runtime.watchdog import full_health_snapshot
from jobtracker.store import llm_queue, llm_reviews
from jobtracker.store.backup import DEFAULT_KEEP_DAYS, backup_career, backup_database
from jobtracker.store.companies import list_discovered, sync_companies
from jobtracker.store.postings import find_duplicates, merge_duplicates
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
    company_sectors = {b.company_slug: b.sector for b in boards}
    profile = load_profile(
        CONFIGS_DIR / "profile.yaml", company_tiers=company_tiers, company_sectors=company_sectors
    )
    tracks = load_tracks(
        CONFIGS_DIR / "profile.yaml",
        CONFIGS_DIR / "tracks.yaml",
        company_tiers=company_tiers,
        company_sectors=company_sectors,
    )
    sources_config = load_sources_config(CONFIGS_DIR / "sources.yaml")
    ctx = CycleContext(
        sources_config=sources_config,
        taxonomy=taxonomy,
        geo=geo,
        profile=profile,
        user_agent=settings.user_agent,
        llm=LlmClientConfig.from_settings(settings),
        tracks=tracks,
    )
    # `source: custom` reads pages as rendered by a headless browser (collect/browser.py).
    ctx.client_factories = {Source.CUSTOM: BrowserClient}
    aggregators = load_aggregators(settings, boards, configs_dir=CONFIGS_DIR)
    if aggregators is not None:
        ctx.collectors.update(aggregators.collectors)
        ctx.client_factories = {**ctx.client_factories, **aggregators.client_factories}
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
        # Naming one company means "look at it now", whatever its refetch cadence says.
        run = run_source_cycle(conn, source, source_boards, ctx=ctx, force=bool(args.company))
    print(
        f"source={run.source.value} status={run.status} fetched={run.fetched} "
        f"new={run.new} updated={run.updated} aliased={run.aliased} rejected={run.rejected} "
        f"requests_made={run.requests_made}",
        file=sys.stderr,
    )
    conn.close()
    return 0


def cmd_collect(args: argparse.Namespace) -> int:
    """One pass over every enabled source, then the deferred LLM queue — and exit.

    The by-hand counterpart of `loop`: no scheduler, no intervals, just "go and look at
    everything once and store it". Sources disabled in `configs/sources.yaml` are skipped.
    Boards refetched too recently are skipped as well (their per-priority cadence) unless
    `--force` is given.
    """
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, boards = _build_context(conn, settings)
    degraded = False
    for source in sorted({b.source for b in boards}, key=lambda s: s.value):
        if not ctx.sources_config.is_enabled(source):
            continue
        source_boards = boards_for_source(boards, source)
        with bound_run_id(str(ULID())):
            run = run_source_cycle(conn, source, source_boards, ctx=ctx, force=args.force)
        degraded = degraded or run.status != "ok"
        print(
            f"source={run.source.value} status={run.status} boards={len(source_boards)} "
            f"fetched={run.fetched} new={run.new} updated={run.updated} aliased={run.aliased} "
            f"rejected={run.rejected} requests_made={run.requests_made}",
            file=sys.stderr,
        )
    _print_tracks(score_tracks(conn, ctx.tracks))
    if ctx.llm is not None:
        with bound_run_id(str(ULID())):
            drain_queue(conn, profile=ctx.profile, cfg=ctx.llm)
            review = review_all(
                conn,
                profile=ctx.profile,
                geo=ctx.geo,
                cfg=ctx.llm,
                limit=ctx.profile.review.max_per_collect,
            )
        print(
            f"llm review: read={review.read} corrected={review.corrected} "
            f"server_available={review.server_available}",
            file=sys.stderr,
        )
        # A correction rescored its posting: the tracks follow.
        _print_tracks(score_tracks(conn, ctx.tracks))
    conn.close()
    return 1 if degraded else 0


def _print_tracks(passes: tuple[TrackPass, ...]) -> None:
    for track in passes:
        tiers = " ".join(f"{tier}={n}" for tier, n in sorted(track.tiers.items()))
        print(
            f"track={track.track.value} scored={track.scored} dropped={track.dropped} {tiers}",
            file=sys.stderr,
        )


def cmd_score_tracks(_args: argparse.Namespace) -> int:
    """Score every stored posting a track has not scored yet — the first run, or by hand."""
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, _boards = _build_context(conn, settings)
    _print_tracks(score_tracks(conn, ctx.tracks))
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
                    score_tracks(conn, ctx.tracks)
                interval_min = ctx.sources_config.interval_min.get(str(source), 180)
                next_due[source] = now_monotonic + interval_min * 60
            if ctx.llm is not None and next_drain <= now_monotonic:
                with bound_run_id(str(ULID())):
                    drain_queue(conn, profile=ctx.profile, cfg=ctx.llm)
                    review_all(
                        conn,
                        profile=ctx.profile,
                        geo=ctx.geo,
                        cfg=ctx.llm,
                        limit=ctx.profile.review.max_per_collect,
                    )
                    score_tracks(conn, ctx.tracks)
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


def cmd_llm_enqueue(_args: argparse.Namespace) -> int:
    """Queue the stored postings the LLM could still help with (see `enqueue_backlog`)."""
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, _boards = _build_context(conn, settings)
    added = enqueue_backlog(conn, profile=ctx.profile)
    print(f"queued={added} depth={llm_queue.depth(conn)}", file=sys.stderr)
    conn.close()
    return 0


def _print_review_summary(stats: ReviewStats, *, dry_run: bool) -> None:
    verb = "would change" if dry_run else "changed"
    print(
        f"read={stats.read} {verb}={stats.corrected} confirmed={stats.confirmed} "
        f"set_aside={stats.set_aside} skipped={stats.skipped} "
        f"server_available={stats.server_available}",
        file=sys.stderr,
    )
    if stats.corrections_by_field:
        fields = ", ".join(f"{k}={v}" for k, v in stats.corrections_by_field.most_common())
        print(f"  by field: {fields}", file=sys.stderr)
    for reason, count in stats.refused.most_common(8):
        print(f"  refused x{count}: {reason}", file=sys.stderr)
    if stats.unknown_cities:
        cities = ", ".join(
            f"{city} ({country or '?'}) x{n}"
            for (city, country), n in stats.unknown_cities.most_common(15)
        )
        print(f"  cities missing from configs/geo.yaml: {cities}", file=sys.stderr)


def cmd_llm_review(args: argparse.Namespace) -> int:
    """Have the local LLM re-read the stored postings and correct what the text contradicts.

    See `runtime.review` and blueprint/wp/WP19-llm-review.md. `--dry-run` writes nothing.
    """
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, _boards = _build_context(conn, settings)
    if ctx.llm is None:
        print("JT_LLM_ENABLED=false: nothing to review with", file=sys.stderr)
        conn.close()
        return 0
    report = open(args.report, "w", encoding="utf-8") if args.report else None  # noqa: SIM115

    def show(step: ReviewStep, stats: ReviewStats) -> None:
        plan = step.plan
        if plan is None:
            return
        if report is not None:
            report.write(
                json.dumps(
                    {
                        "posting_id": step.posting_id,
                        "title": step.title,
                        "outcome": plan.outcome.value,
                        "confidence": plan.confidence,
                        "corrections": [c.model_dump(mode="json") for c in plan.corrections],
                        "refused": list(plan.refused),
                        "model_said": None
                        if step.output is None
                        else step.output.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            report.flush()
        for correction in plan.corrections:
            print(
                f"  {step.title[:50]:<50} {correction.field}: "
                f"{correction.before} -> {correction.after}",
                file=sys.stderr,
                flush=True,
            )
        if stats.read % args.every == 0:
            print(f"[{stats.read}] changed={stats.corrected}", file=sys.stderr, flush=True)

    try:
        with bound_run_id(str(ULID())):
            stats = review_all(
                conn,
                profile=ctx.profile,
                geo=ctx.geo,
                cfg=ctx.llm,
                limit=args.limit,
                dry_run=args.dry_run,
                posting_ids=[args.posting_id] if args.posting_id else None,
                on_step=show,
            )
    finally:
        if report is not None:
            report.close()
    _print_review_summary(stats, dry_run=args.dry_run)
    if not args.dry_run:
        remaining = len(
            llm_reviews.unreviewed_posting_ids(conn, review_version=ctx.profile.review.version)
        )
        print(f"  still unread: {remaining}", file=sys.stderr)
    conn.close()
    return 0


def cmd_llm_revert(args: argparse.Namespace) -> int:
    """Undo the LLM's corrections of one field and queue those postings to be read again."""
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, _boards = _build_context(conn, settings)
    count = revert_corrections(
        conn,
        field=args.field,
        profile=ctx.profile,
        geo=ctx.geo,
        posting_ids=args.posting_id or None,
    )
    print(f"reverted={count} field={args.field} (they will be read again)", file=sys.stderr)
    conn.close()
    return 0


def cmd_llm_drain(args: argparse.Namespace) -> int:
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    ctx, _boards = _build_context(conn, settings)
    if ctx.llm is None:
        print("JT_LLM_ENABLED=false: nothing to drain", file=sys.stderr)
        conn.close()
        return 0
    with bound_run_id(str(ULID())):
        if args.all:
            result = drain_all(
                conn,
                profile=ctx.profile,
                cfg=ctx.llm,
                on_batch=lambda r: print(
                    f"  resolved={r.resolved} quarantined={r.quarantined} "
                    f"dropped={r.dropped} remaining={r.remaining}",
                    file=sys.stderr,
                    flush=True,
                ),
            )
        else:
            result = drain_queue(conn, profile=ctx.profile, cfg=ctx.llm)
    print(
        f"resolved={result.resolved} quarantined={result.quarantined} dropped={result.dropped} "
        f"requeued={result.requeued} remaining={result.remaining} "
        f"server_available={result.server_available}",
        file=sys.stderr,
    )
    conn.close()
    return 0


def cmd_dedupe_postings(args: argparse.Namespace) -> int:
    """Identical live postings on one board: a dry run by default, like `replay`."""
    settings = load_settings()
    conn = _connect_and_migrate(settings)
    groups, left_alone = find_duplicates(conn)
    extra = sum(len(group.drop) for group in groups)
    print(f"{len(groups)} groups, {extra} postings to merge; {len(left_alone)} left alone")
    for ids in left_alone:
        print(f"  left alone, each carries the user's marks: {', '.join(ids)}")
    if args.apply:
        for group in groups:
            merge_duplicates(conn, group)
        conn.commit()
        print(f"{extra} postings merged")
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
    career = backup_career(settings.career_root, Path(args.dest), now=utc_now())
    if career is None:
        print(f"no folder to archive at {settings.career_root}", file=sys.stderr)
    else:
        print(f"backup written: {career}", file=sys.stderr)
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


def cmd_import_applications(args: argparse.Namespace) -> int:
    """Read the spreadsheet export and the folder of past applications, reconcile them, and
    (with --apply) copy the files under the career directory and write `applications`."""
    settings = load_settings()
    sheet = parse_sheet(Path(args.sheet).read_text(encoding="utf-8"))
    dossier_root = Path(args.dossier)
    dossier = scan_dossier(dossier_root)
    conn = _connect_and_migrate(settings)
    outcome = import_history(
        conn,
        sheet=sheet,
        dossier=dossier,
        dossier_root=dossier_root,
        aliases_config=load_yaml(CONFIGS_DIR / "company_aliases.yaml"),
        boards=load_registry(CONFIGS_DIR / "companies.yaml"),
        career_root=settings.career_root,
        apply=args.apply,
    )
    conn.close()
    lines = report_lines(sheet, dossier, outcome)
    if args.report:
        Path(args.report).write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    result = outcome.reconciliation
    print(
        f"sheet: {len(sheet.rows)} rows, {len(sheet.issues)} unreadable · "
        f"folders: {len(dossier.entries)}, {len(dossier.skipped)} skipped\n"
        f"applications: {len(result.applications)} — paired {result.paired}, "
        f"sharing a folder {result.shared}, sheet only {result.sheet_only}, "
        f"folder only {result.folder_only}, ambiguous {len(result.ambiguities)}\n"
        f"companies outside the registry: {len(result.unresolved_companies)}",
        file=sys.stderr,
    )
    if args.apply:
        print(
            f"written {outcome.written}, {outcome.kept_edited} left alone (edited by hand), "
            f"purged {outcome.purged} stale ({outcome.kept_stale} kept: edited by hand), "
            f"copied {outcome.files_copied} "
            f"files under {settings.career_root / 'applications'}",
            file=sys.stderr,
        )
    else:
        print("dry run — nothing written; --apply to import", file=sys.stderr)
    return 0


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

    collect = subparsers.add_parser("collect", help="one pass over every enabled source, then exit")
    collect.add_argument(
        "--force", action="store_true", help="ignore the per-board refetch cadence"
    )
    collect.set_defaults(func=cmd_collect)

    subparsers.add_parser("loop", help="run continuously").set_defaults(func=cmd_loop)

    subparsers.add_parser(
        "score-tracks", help="score stored postings against every track of configs/tracks.yaml"
    ).set_defaults(func=cmd_score_tracks)

    subparsers.add_parser(
        "llm-enqueue", help="queue stored postings the LLM could still help with"
    ).set_defaults(func=cmd_llm_enqueue)

    review = subparsers.add_parser(
        "llm-review", help="have the LLM re-read stored postings and correct their fields"
    )
    review.add_argument("--limit", type=int, default=None, help="read at most this many")
    review.add_argument(
        "--dry-run", action="store_true", help="show what would change, write nothing"
    )
    review.add_argument("--posting-id", default=None, help="read this one posting only")
    review.add_argument("--report", default=None, help="write one JSON line per posting here")
    review.add_argument("--every", type=int, default=25, help="progress line every N postings")
    review.set_defaults(func=cmd_llm_review)

    revert = subparsers.add_parser(
        "llm-revert", help="undo the LLM's corrections of one field and read those postings again"
    )
    revert.add_argument("--field", required=True, choices=REVERTIBLE_FIELDS)
    revert.add_argument(
        "--posting-id", action="append", default=None, help="only this posting (repeatable)"
    )
    revert.set_defaults(func=cmd_llm_revert)

    llm_drain = subparsers.add_parser("llm-drain", help="one pass over the deferred LLM queue")
    llm_drain.add_argument(
        "--all", action="store_true", help="keep going until the queue is empty or the server stops"
    )
    llm_drain.set_defaults(func=cmd_llm_drain)

    subparsers.add_parser(
        "discover-employers", help="employers seen only at aggregators, for the registry"
    ).set_defaults(func=cmd_discover_employers)

    dedupe = subparsers.add_parser("dedupe-postings", help="merge identical live postings")
    dedupe.add_argument("--apply", action="store_true", help="write; the default is a dry run")
    dedupe.set_defaults(func=cmd_dedupe_postings)

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

    imp = subparsers.add_parser(
        "import-applications",
        help="import the application history: spreadsheet CSV + folder of screenshots/CVs",
    )
    imp.add_argument("--sheet", required=True, help="the spreadsheet, exported as CSV")
    imp.add_argument("--dossier", required=True, help="the folder: <company>/<job>/files")
    imp.add_argument("--apply", action="store_true", help="write; the default is a dry run")
    imp.add_argument("--report", help="write the review report (JSONL) to this file")
    imp.set_defaults(func=cmd_import_applications)

    add_app_parser(subparsers)

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
