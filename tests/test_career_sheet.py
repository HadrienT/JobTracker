"""The calendar-shaped spreadsheet export — blueprint/wp/WP21-applications.md §3."""

from datetime import date

from jobtracker.career.sheet import parse_sheet

# Two layouts, as in the real export: 5-column blocks side by side, then a 6-column one with
# `Job`. Month markers, totals and blank separator columns in between. Fictional employers.
_HEADER_5 = "Country,Company,Application date,Rejection date,Reason"
_SHEET = f"""\
{_HEADER_5},,{_HEADER_5}
May,,,,,,July,,,,
CH (Zurich),Acme Quant,27/05/2024,04/07/2024,Failed 2nd interview,,\
CH (Geneva),Borealis Fund,10/07/2024,,Waiting for answer
CH (Basel),Cobalt Labs,?,13/06/2024,Not interested,,,,,,
4,1,,,,,2,0,,,
Country,Company,Job,Application date,Rejection date,Reason,,,,,
October,,,,,,,,,,
USA (New York) NY,Delta Trading,"Quant Dev
",07/10/2026,,Waiting for answer,,,,,
UK (London),Echo Capital,SWE,32/10/2026,,Waiting for answer,,,,,
"""


def test_every_application_of_every_block_and_layout_is_read() -> None:
    parsed = parse_sheet(_SHEET)
    assert [row.company for row in parsed.rows] == [
        "Acme Quant",
        "Borealis Fund",
        "Cobalt Labs",
        "Delta Trading",
    ]


def test_month_markers_and_totals_are_not_applications_nor_issues() -> None:
    parsed = parse_sheet(_SHEET)
    assert all(issue.message == "unreadable date" for issue in parsed.issues)


def test_dates_are_day_first_and_a_question_mark_is_a_known_unknown() -> None:
    rows = {row.company: row for row in parse_sheet(_SHEET).rows}
    assert rows["Acme Quant"].applied.day == date(2024, 5, 27)
    assert rows["Acme Quant"].closed.day == date(2024, 7, 4)
    assert rows["Cobalt Labs"].applied.day is None
    assert rows["Cobalt Labs"].applied.unknown_marked
    assert rows["Borealis Fund"].closed.day is None
    assert not rows["Borealis Fund"].closed.unknown_marked


def test_the_job_column_only_exists_from_its_header_on() -> None:
    rows = {row.company: row for row in parse_sheet(_SHEET).rows}
    assert rows["Acme Quant"].title is None
    assert rows["Delta Trading"].title == "Quant Dev"  # the stray newline is gone


def test_an_impossible_date_is_reported_with_its_line_never_guessed() -> None:
    parsed = parse_sheet(_SHEET)
    assert len(parsed.issues) == 1
    issue = parsed.issues[0]
    assert issue.line == 9
    assert "Echo Capital" in issue.cells
