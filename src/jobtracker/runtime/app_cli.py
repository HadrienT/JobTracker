"""`jobtracker app …` — applications by hand — blueprint/wp/WP21-applications.md.

Nothing here needs the collector: an offer seen on LinkedIn, a recruiter's email, a referral is
recorded like any other — company and title typed in, the offer archived from its URL or from
pasted text, files attached, status moved along. When the posting *is* collected, `--posting`
takes everything from it, through the very code path the feed uses (`api.tracking`).

Ids are long; any unique prefix will do, as with git.
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import date
from pathlib import Path

from ulid import ULID

from jobtracker.api.tracking import (
    OFFER_PDF,
    PendingPdf,
    offer_sheet,
    render_pending,
    track_posting,
)
from jobtracker.career.lifecycle import is_abandoned, is_open
from jobtracker.career.names import alias_map, company_key
from jobtracker.career.offer import OfferSheet, write_offer_pdf, write_pdf
from jobtracker.collect.browser import BrowserClient
from jobtracker.collect.registry import load_registry
from jobtracker.core.clock import utc_now
from jobtracker.core.config import Settings, load_settings, load_yaml
from jobtracker.core.db import apply_migrations, connect
from jobtracker.core.enums import ApplicationOrigin, ApplicationStatus
from jobtracker.core.errors import CollectError, RenderError
from jobtracker.core.models import Application, ApplicationEvent
from jobtracker.runtime.applications import adopt_feed_statuses, registry_keys
from jobtracker.store.applications import (
    create_application,
    delete_application,
    dossier_name,
    get_application,
    link_posting,
    list_applications,
    match_application_ids,
    record_status,
    update_application,
)
from jobtracker.store.postings import PostingRow, get_posting_row
from jobtracker.store.schema import MIGRATIONS_DIR

CONFIGS_DIR = Path(__file__).resolve().parents[3] / "configs"


class _Fail(Exception):
    """A usage error: printed, exit code 2."""


def _open() -> tuple[Settings, sqlite3.Connection]:
    settings = load_settings()
    conn = connect(settings.db_path)
    apply_migrations(conn, MIGRATIONS_DIR)
    return settings, conn


def _resolve(conn: sqlite3.Connection, prefix: str) -> Application:
    ids = match_application_ids(conn, prefix)
    if not ids:
        raise _Fail(f"no application id starts with {prefix!r}")
    if len(ids) > 1:
        raise _Fail(f"{prefix!r} is ambiguous: {', '.join(i[:12] for i in ids[:8])}")
    application = get_application(conn, ids[0])
    assert application is not None
    return application


def _folder(settings: Settings, application: Application) -> Path | None:
    if application.dossier is None:
        return None
    return settings.career_root / "applications" / application.dossier


def _day(text: str | None) -> date:
    return date.fromisoformat(text) if text else utc_now().date()


def _status(text: str) -> ApplicationStatus:
    try:
        return ApplicationStatus(text)
    except ValueError:
        choices = ", ".join(s.value for s in ApplicationStatus)
        raise _Fail(f"unknown status {text!r} — one of {choices}") from None


def _posting_by_url(conn: sqlite3.Connection, url: str) -> PostingRow | None:
    row = conn.execute(
        "SELECT posting_id FROM postings WHERE url = ? UNION "
        "SELECT canonical_id FROM posting_aliases WHERE url = ? LIMIT 1",
        (url, url),
    ).fetchone()
    return get_posting_row(conn, row[0]) if row is not None else None


def _aliases() -> dict[str, str]:
    return alias_map(load_yaml(CONFIGS_DIR / "company_aliases.yaml"))


def _company_slug(name: str) -> str | None:
    aliases = _aliases()
    boards = load_registry(CONFIGS_DIR / "companies.yaml")
    return registry_keys(boards, aliases).get(company_key(name, aliases))


def _archive_offer(target: Path, *, sheet: OfferSheet | None, url: str | None, today: date) -> str:
    """Write the offer PDF from typed-in text if any, else by printing the live page."""
    try:
        if sheet is not None:
            write_offer_pdf(sheet, target, archived_on=today)
            return f"offer archived (typeset) → {target}"
        if url is not None:
            with BrowserClient() as browser:
                write_pdf(browser.print_pdf(url), target)
            return f"offer archived (printed from the page) → {target}"
    except (RenderError, CollectError) as exc:
        return f"offer NOT archived: {exc} — retry with `jobtracker app pdf`"
    return "no offer archived — give --url or --text (or `jobtracker app pdf` later)"


def _copy_in(folder: Path, files: list[str]) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in files:
        source = Path(name).expanduser()
        if not source.is_file():
            raise _Fail(f"no such file: {source}")
        target = folder / source.name
        shutil.copy2(source, target)
        copied.append(target)
    return copied


# --- commands ------------------------------------------------------------------------------


def _line(application: Application, today: date) -> str:
    status = application.status.value
    if is_abandoned(application, today):
        status += " (5+ months)"
    day = application.applied_on.isoformat() if application.applied_on else "?"
    if application.applied_on_estimated:
        day += "~"
    where = f" · {application.location}" if application.location else ""
    return (
        f"{application.application_id[:10]}  {day:11} {status:22} "
        f"{application.company} — {application.title or '(no title)'}{where}"
    )


def cmd_list(args: argparse.Namespace) -> int:
    _, conn = _open()
    today = utc_now().date()
    shown = list_applications(conn)
    if args.open:
        shown = [a for a in shown if is_open(a, today)]
    if args.status:
        shown = [a for a in shown if a.status is _status(args.status)]
    if args.company:
        needle = args.company.lower()
        shown = [a for a in shown if needle in a.company.lower()]
    for application in shown[: args.limit] if args.limit else shown:
        print(_line(application, today))
    every = list_applications(conn)
    print(
        f"{len(shown)} shown · {sum(is_open(a, today) for a in every)} open · "
        f"{sum(is_abandoned(a, today) for a in every)} with no news for 5+ months · "
        f"{len(every)} in all",
        file=sys.stderr,
    )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    settings, conn = _open()
    a = _resolve(conn, args.id)
    print(f"id        {a.application_id}")
    print(f"company   {a.company}" + (f"  [{a.company_slug}]" if a.company_slug else ""))
    print(f"title     {a.title or '—'}")
    print(f"location  {a.location or '—'}")
    applied = a.applied_on.isoformat() if a.applied_on else "?"
    print(f"applied   {applied}{' (estimated)' if a.applied_on_estimated else ''}")
    print(f"status    {a.status.value}" + (f" — {a.reason}" if a.reason else ""))
    if is_abandoned(a, utc_now().date()):
        print("          no news for 5+ months: counted as abandoned")
    print(f"posting   {a.posting_id or '—'}")
    print(f"origin    {a.origin.value}")
    for event in a.events:
        when = event.on_date.isoformat() if event.on_date else "?"
        print(f"  {when:10}  {event.status.value}" + (f" — {event.reason}" if event.reason else ""))
    if a.note:
        print(f"note      {a.note}")
    folder = _folder(settings, a)
    if folder is not None:
        print(f"folder    {folder}")
        if folder.is_dir():
            for path in sorted(folder.iterdir()):
                print(f"  {path.name}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    settings, conn = _open()
    day = _day(args.date)
    status = _status(args.status)
    row = get_posting_row(conn, args.posting) if args.posting else None
    if args.posting and row is None:
        raise _Fail(f"no such posting: {args.posting}")
    if row is None and args.url and args.text is None:
        row = _posting_by_url(conn, args.url)
        if row is not None:
            print(f"this URL is a collected posting: {row.posting_id}", file=sys.stderr)
    if row is not None:
        tracked = track_posting(
            conn,
            row,
            status,
            today=day,
            career_root=settings.career_root,
            aliases=_aliases(),
            origin=ApplicationOrigin.CLI,
        )
        application = tracked.application
        assert application is not None
        if tracked.linked:
            print("linked to an application already recorded", file=sys.stderr)
        if tracked.pdf is not None:
            done = render_pending(tracked.pdf, today=utc_now().date())
            print(
                f"offer archived → {tracked.pdf.target}" if done else "offer NOT archived",
                file=sys.stderr,
            )
    else:
        if not (args.company and args.title):
            raise _Fail("give --posting, a collected --url, or --company and --title")
        events = [ApplicationEvent(on_date=day, status=ApplicationStatus.APPLIED)]
        if status is not ApplicationStatus.APPLIED:
            events.append(ApplicationEvent(on_date=day, status=status))
        application = Application(
            application_id=str(ULID()),
            company=args.company,
            company_slug=_company_slug(args.company),
            title=args.title,
            location=args.location,
            applied_on=day,
            applied_on_estimated=False,
            closed_on=None,
            status=status,
            reason="",
            posting_id=None,
            dossier=dossier_name(day, args.company, args.title),
            origin=ApplicationOrigin.CLI,
            note=args.note or "",
            events=tuple(events),
        )
        create_application(conn, application)
        conn.commit()
        folder = _folder(settings, application)
        assert folder is not None
        sheet = None
        if args.text is not None:
            text = sys.stdin.read() if args.text == "-" else Path(args.text).read_text("utf-8")
            sheet = OfferSheet(
                title=args.title,
                company=args.company,
                description=text,
                locations=(args.location,) if args.location else (),
                url=args.url,
                applied_on=day,
            )
        message = _archive_offer(
            folder / OFFER_PDF, sheet=sheet, url=args.url, today=utc_now().date()
        )
        print(message, file=sys.stderr)
    if args.note and row is not None:
        update_application(conn, application.application_id, note=args.note)
        conn.commit()
    folder = _folder(settings, application)
    if args.attach and folder is not None:
        for path in _copy_in(folder, args.attach):
            print(f"attached → {path}", file=sys.stderr)
    print(application.application_id)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    _, conn = _open()
    application = _resolve(conn, args.id)
    record_status(
        conn,
        application.application_id,
        _status(args.status),
        on_date=_day(args.date),
        reason=args.reason,
    )
    conn.commit()
    updated = get_application(conn, application.application_id)
    assert updated is not None
    print(_line(updated, utc_now().date()))
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    _, conn = _open()
    application = _resolve(conn, args.id)
    columns: dict[str, object] = {}
    for name in ("title", "company", "location", "note"):
        if getattr(args, name) is not None:
            columns[name] = getattr(args, name)
    if args.company is not None:
        columns["company_slug"] = _company_slug(args.company)
    if args.date is not None:
        columns["applied_on"] = _day(args.date).isoformat()
    if not columns:
        raise _Fail("nothing to change — --title, --company, --location, --date, --note")
    update_application(conn, application.application_id, **columns)
    conn.commit()
    updated = get_application(conn, application.application_id)
    assert updated is not None
    print(_line(updated, utc_now().date()))
    return 0


def cmd_link(args: argparse.Namespace) -> int:
    _, conn = _open()
    application = _resolve(conn, args.id)
    posting_id = None if args.posting == "none" else args.posting
    if posting_id is not None and get_posting_row(conn, posting_id) is None:
        raise _Fail(f"no such posting: {posting_id}")
    link_posting(conn, application.application_id, posting_id)
    conn.commit()
    print(f"{application.application_id[:10]} → {posting_id or 'unlinked'}")
    return 0


def cmd_attach(args: argparse.Namespace) -> int:
    settings, conn = _open()
    application = _resolve(conn, args.id)
    folder = _folder(settings, application)
    if folder is None:
        name = dossier_name(
            application.applied_on or utc_now().date(), application.company, application.title
        )
        update_application(conn, application.application_id, dossier=name)
        conn.commit()
        folder = settings.career_root / "applications" / name
    for path in _copy_in(folder, args.files):
        print(f"attached → {path}")
    return 0


def cmd_pdf(args: argparse.Namespace) -> int:
    settings, conn = _open()
    application = _resolve(conn, args.id)
    folder = _folder(settings, application)
    if folder is None:
        raise _Fail("this application has no folder — `jobtracker app attach` creates one")
    target = folder / OFFER_PDF
    today = utc_now().date()
    row = get_posting_row(conn, application.posting_id) if application.posting_id else None
    if args.text is None and args.url is None and row is not None:
        pending = PendingPdf(
            application.application_id, offer_sheet(conn, row, application.applied_on), target
        )
        ok = render_pending(pending, today=today)
        print(f"offer archived → {target}" if ok else "offer NOT archived (see the log)")
        return 0 if ok else 1
    sheet = None
    if args.text is not None:
        text = sys.stdin.read() if args.text == "-" else Path(args.text).read_text("utf-8")
        sheet = OfferSheet(
            title=application.title or "(no title)",
            company=application.company,
            description=text,
            locations=(application.location,) if application.location else (),
            url=args.url,
            applied_on=application.applied_on,
        )
    message = _archive_offer(target, sheet=sheet, url=args.url, today=today)
    print(message)
    return 0 if "NOT" not in message and "no offer" not in message else 1


def cmd_rm(args: argparse.Namespace) -> int:
    _, conn = _open()
    application = _resolve(conn, args.id)
    if not args.yes:
        raise _Fail(f"would delete {_line(application, utc_now().date())} — add --yes")
    delete_application(conn, application.application_id)
    conn.commit()
    print("deleted (its folder, if any, is left on disk)")
    return 0


def cmd_adopt_feed(args: argparse.Namespace) -> int:
    settings, conn = _open()
    adoption = adopt_feed_statuses(
        conn,
        career_root=settings.career_root,
        aliases_config=load_yaml(CONFIGS_DIR / "company_aliases.yaml"),
        apply=args.apply,
        render=args.apply and args.pdf,
    )
    for posting_id, application_id in adoption.linked:
        print(f"link     {posting_id} → application {application_id[:10]}")
    for posting_id in adoption.created:
        print(f"create   {posting_id}")
    for posting_id in adoption.triaged:
        print(f"triage   {posting_id} (withdrawn, never applied: now a 'no')")
    for posting_id, candidates in adoption.ambiguous:
        print(f"AMBIGUOUS {posting_id}: {', '.join(c[:10] for c in candidates)} — left as it is")
    print(
        f"{len(adoption.linked)} linked, {len(adoption.created)} created, "
        f"{len(adoption.triaged)} triaged, {len(adoption.ambiguous)} ambiguous"
        + (f", {adoption.pdfs_failed} PDFs failed" if adoption.pdfs_failed else ""),
        file=sys.stderr,
    )
    if not args.apply:
        print("dry run — nothing written; --apply to do it", file=sys.stderr)
    return 0


def _guarded(command: object) -> object:
    def run(args: argparse.Namespace) -> int:
        try:
            result: int = command(args)  # type: ignore[operator]
        except _Fail as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return result

    return run


def add_app_parser(subparsers: "argparse._SubParsersAction[argparse.ArgumentParser]") -> None:
    app = subparsers.add_parser("app", help="applications, by hand (WP21)")
    commands = app.add_subparsers(dest="app_command", required=True)

    listing = commands.add_parser("list", help="every application, newest first")
    listing.add_argument("--open", action="store_true", help="only those still worth waiting on")
    listing.add_argument("--status", help="only this status")
    listing.add_argument("--company", help="company name contains")
    listing.add_argument("--limit", type=int, default=0)
    listing.set_defaults(func=_guarded(cmd_list))

    show = commands.add_parser("show", help="one application, its history and files")
    show.add_argument("id")
    show.set_defaults(func=_guarded(cmd_show))

    add = commands.add_parser("add", help="record an application (collected posting or not)")
    add.add_argument("--posting", help="a collected posting id: everything comes from it")
    add.add_argument("--company")
    add.add_argument("--title")
    add.add_argument("--location")
    add.add_argument("--url", help="the offer's page: a collected posting, or printed to PDF")
    add.add_argument("--text", help="the offer's text (a file, or - for stdin), typeset to PDF")
    add.add_argument("--date", help="YYYY-MM-DD; default today")
    add.add_argument("--status", default="applied")
    add.add_argument("--note")
    add.add_argument("--attach", nargs="+", help="files to copy in: the CV sent, a letter…")
    add.set_defaults(func=_guarded(cmd_add))

    status = commands.add_parser("status", help="move an application along")
    status.add_argument("id")
    status.add_argument("status", help=", ".join(s.value for s in ApplicationStatus))
    status.add_argument("--date", help="YYYY-MM-DD; default today")
    status.add_argument("--reason", help='their words: "Failed 2nd interview", "Job filled"…')
    status.set_defaults(func=_guarded(cmd_status))

    edit = commands.add_parser("edit", help="fix what was recorded")
    edit.add_argument("id")
    for name in ("--title", "--company", "--location", "--note"):
        edit.add_argument(name)
    edit.add_argument("--date", help="the application date, YYYY-MM-DD")
    edit.set_defaults(func=_guarded(cmd_edit))

    link = commands.add_parser("link", help="tie to a collected posting ('none' unties)")
    link.add_argument("id")
    link.add_argument("posting")
    link.set_defaults(func=_guarded(cmd_link))

    attach = commands.add_parser("attach", help="copy files into the application's folder")
    attach.add_argument("id")
    attach.add_argument("files", nargs="+")
    attach.set_defaults(func=_guarded(cmd_attach))

    pdf = commands.add_parser("pdf", help="(re)archive the offer as offer.pdf")
    pdf.add_argument("id")
    pdf.add_argument("--url", help="print this page instead")
    pdf.add_argument("--text", help="typeset this text instead (a file, or - for stdin)")
    pdf.set_defaults(func=_guarded(cmd_pdf))

    rm = commands.add_parser("rm", help="delete an application (files stay on disk)")
    rm.add_argument("id")
    rm.add_argument("--yes", action="store_true")
    rm.set_defaults(func=_guarded(cmd_rm))

    adopt = commands.add_parser(
        "adopt-feed", help="turn statuses set in the feed before WP21 into applications"
    )
    adopt.add_argument("--apply", action="store_true", help="write; the default is a dry run")
    adopt.add_argument("--no-pdf", dest="pdf", action="store_false", help="skip offer PDFs")
    adopt.set_defaults(func=_guarded(cmd_adopt_feed))
