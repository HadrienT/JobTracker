"""Sheet rows ↔ folders → applications — WP21 §3."""

from datetime import date

from jobtracker.career.dossier import DossierEntry, FileKind
from jobtracker.career.reconcile import reconcile
from jobtracker.career.sheet import SheetDate, SheetRow
from jobtracker.core.enums import ApplicationStatus


def _row(
    company: str,
    applied: date | None,
    *,
    title: str | None = None,
    location: str = "",
    closed: date | None = None,
    reason: str = "Waiting for answer",
    line: int = 1,
) -> SheetRow:
    return SheetRow(
        line=line,
        block=0,
        location=location,
        company=company,
        title=title,
        applied=SheetDate(day=applied),
        closed=SheetDate(day=closed),
        reason=reason,
    )


def _entry(relative: str, first_seen: date | None) -> DossierEntry:
    company, _, role = relative.partition("/")
    return DossierEntry(
        company=company,
        role=role or None,
        relative=relative,
        files={"1.png": FileKind.OFFER},
        first_seen=first_seen,
    )


def _run(rows: list[SheetRow], entries: list[DossierEntry]):  # type: ignore[no-untyped-def]
    return reconcile(rows, entries, aliases={}, registry={"acme": "acme_slug"})


def test_title_and_place_pick_the_right_folder_on_a_busy_day() -> None:
    day = date(2026, 10, 7)
    rows = [
        _row("Acme", day, title="Quant Dev", location="USA (New York) NY", line=1),
        _row("Acme", day, title="Quant Dev", location="Singapore", line=2),
    ]
    entries = [_entry("Acme/Quant Dev SG", day), _entry("Acme/Quant Dev NY", day)]
    result = _run(rows, entries)
    by_location = {a.location: a.dossier for a in result.applications}
    assert by_location == {
        "USA (New York) NY": "Acme/Quant Dev NY",
        "Singapore": "Acme/Quant Dev SG",
    }
    assert result.paired == 2


def test_dates_a_month_apart_are_different_applications() -> None:
    result = _run([_row("Acme", date(2024, 11, 15))], [_entry("Acme/Old", date(2026, 3, 20))])
    assert (result.sheet_only, result.folder_only) == (1, 1)


def test_a_true_tie_is_reported_not_guessed() -> None:
    day = date(2026, 3, 20)
    rows = [
        _row("Acme", day, closed=date(2026, 3, 25), reason="Not interested", line=1),
        _row("Acme", day, line=2),
    ]
    entries = [_entry("Acme/Analyst", day), _entry("Acme/SWE", day)]
    result = _run(rows, entries)
    assert {a.row.line for a in result.ambiguities} == {1, 2}
    assert result.paired == 0


def test_identical_rows_tie_by_nature_and_are_paired_in_order() -> None:
    day = date(2026, 10, 20)
    rows = [_row("Acme", day, title="Quant Dev", location="UK (London)", line=n) for n in (1, 2)]
    entries = [_entry("Acme/Quant Dev UK", day), _entry("Acme/Quant Dev UK 2", day)]
    result = _run(rows, entries)
    assert not result.ambiguities
    assert sorted(a.dossier or "" for a in result.applications) == [
        "Acme/Quant Dev UK",
        "Acme/Quant Dev UK 2",
    ]
    assert len({a.application_id for a in result.applications}) == 2


def test_one_folder_may_serve_two_rows_sent_the_same_day() -> None:
    day = date(2025, 1, 27)
    rows = [_row("Acme (Quant)", day, line=1), _row("Acme (SWE)", day, line=2)]
    result = _run(rows, [_entry("Acme", day)])
    assert [a.dossier for a in result.applications] == ["Acme", "Acme"]
    assert result.shared == 1


def test_status_and_history_follow_the_reason() -> None:
    applied, closed = date(2024, 5, 27), date(2024, 7, 4)
    result = _run(
        [
            _row("Acme", applied, closed=closed, reason="Failed 2nd interview", line=1),
            _row("Borealis", applied, line=2),
        ],
        [],
    )
    by_company = {a.company: a for a in result.applications}
    failed = by_company["Acme"]
    assert failed.status is ApplicationStatus.REJECTED
    assert [e.status for e in failed.events] == [
        ApplicationStatus.APPLIED,
        ApplicationStatus.INTERVIEW,
        ApplicationStatus.REJECTED,
    ]
    assert failed.reason == "Failed 2nd interview"
    assert failed.company_slug == "acme_slug"
    assert by_company["Borealis"].status is ApplicationStatus.APPLIED
    assert result.unresolved_companies == ["Borealis"]


def test_a_folder_alone_still_counts_with_an_estimated_date() -> None:
    result = _run([], [_entry("Acme/SWE", date(2026, 3, 11))])
    (application,) = result.applications
    assert application.applied_on == date(2026, 3, 11)
    assert application.applied_on_estimated
    assert application.title == "SWE"


def test_a_date_named_folder_dates_itself() -> None:
    result = _run([], [_entry("Acme/08-12-2024", date(2025, 6, 1))])
    (application,) = result.applications
    assert application.applied_on == date(2024, 12, 8)
    assert not application.applied_on_estimated
    assert application.title is None


def test_ids_are_stable_across_runs() -> None:
    rows = [_row("Acme", date(2026, 1, 5), title="SWE")]
    assert [a.application_id for a in _run(rows, []).applications] == [
        a.application_id for a in _run(rows, []).applications
    ]
