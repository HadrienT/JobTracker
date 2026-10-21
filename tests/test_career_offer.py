"""The offer as a clean PDF — WP21 §4."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from jobtracker.career.offer import (
    OfferSheet,
    compensation_label,
    html_to_pdf,
    location_label,
    offer_html,
    write_offer_pdf,
)
from jobtracker.core.enums import RemoteMode, SalaryPeriod
from jobtracker.core.models import Compensation, Location

_SHEET = OfferSheet(
    title="Quant Dev <C++>",
    company="Acme & Co",
    description=(
        "About us\n\nWe price things.\n\nRequirements:\n- C++20\n- Python\n\nWHAT WE OFFER\n• Lunch"
    ),
    locations=("London, GB",),
    compensation="GBP 90,000 – 110,000 per year",
    url="https://example.com/jobs/1?a=1&b=2",
    applied_on=date(2026, 10, 21),
)


def test_the_page_escapes_what_it_is_given() -> None:
    page = offer_html(_SHEET, archived_on=date(2026, 10, 21))
    assert "Quant Dev &lt;C++&gt;" in page
    assert "Acme &amp; Co" in page
    assert "a=1&amp;b=2" in page


def test_plain_text_becomes_paragraphs_lists_and_headings() -> None:
    page = offer_html(_SHEET, archived_on=date(2026, 10, 21))
    assert "<ul><li>C++20</li><li>Python</li></ul>" in page
    assert "<h3>Requirements:</h3>" in page
    assert "<h3>WHAT WE OFFER</h3>" in page
    assert "<p>We price things.</p>" in page


def test_the_page_loads_nothing_from_anywhere() -> None:
    page = offer_html(_SHEET, archived_on=date(2026, 10, 21))
    assert "<script" not in page
    assert "<link" not in page
    assert "src=" not in page


def test_labels() -> None:
    hybrid = Location(
        city="London", country="GB", region="emea", remote_mode=RemoteMode.HYBRID, raw=None
    )
    assert location_label(hybrid) == "London, GB (hybrid)"
    pay = Compensation(
        amount_min=Decimal(90000),
        amount_max=Decimal(110000),
        currency="GBP",
        period=SalaryPeriod.YEAR,
        bonus_mentioned=True,
        equity_mentioned=False,
        raw=None,
    )
    assert compensation_label(pay) == "GBP 90,000 – 110,000 per year + bonus"


@pytest.mark.browser
def test_chromium_prints_a_real_pdf(tmp_path: Path) -> None:
    target = tmp_path / "offer.pdf"
    write_offer_pdf(_SHEET, target, archived_on=date(2026, 10, 21))
    assert target.read_bytes().startswith(b"%PDF")
    assert not list(tmp_path.glob("*.part"))
    assert html_to_pdf("<p>x</p>").startswith(b"%PDF")
