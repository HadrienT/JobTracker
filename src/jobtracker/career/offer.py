"""The offer, as a clean PDF — blueprint/wp/WP21-applications.md §4.

A screenshot of a career page is the page's layout, cookie banner included, and it is gone the
day the page is. What is archived instead is the posting itself, typeset: who, what, where, how
much, the link, the dates, then the full description. `offer_html` builds the page (pure);
`html_to_pdf` prints it with headless Chromium, offline — the page loads nothing from anywhere.
"""

import html
import os
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from jobtracker.core.enums import SalaryPeriod, VisaStatus
from jobtracker.core.errors import RenderError
from jobtracker.core.models import Compensation, Location

_BULLET = re.compile(r"^\s*(?:[-•*·▪●◦]|\d{1,2}[.)])\s+")
_HEADING = re.compile(r"^[^.!?]{2,70}:$|^[A-Z][A-Z &/'-]{3,60}$")
_PERIODS = {
    SalaryPeriod.YEAR: "per year",
    SalaryPeriod.MONTH: "per month",
    SalaryPeriod.DAY: "per day",
    SalaryPeriod.HOUR: "per hour",
}
_VISA = {
    VisaStatus.SPONSORS: "Sponsors visas",
    VisaStatus.NO: "No visa sponsorship",
}


@dataclass(frozen=True)
class OfferSheet:
    """What the PDF shows: a collected posting, or an offer typed in by hand."""

    title: str
    company: str
    description: str
    locations: tuple[str, ...] = ()
    compensation: str | None = None
    visa: str | None = None
    url: str | None = None
    seen_on: date | None = None  # when JobTracker first saw it
    applied_on: date | None = None
    extra: dict[str, str] = field(default_factory=dict)


class PostingLike(Protocol):
    """What the PDF reads off a collected posting (`store.postings.PostingRow` fits)."""

    @property
    def title_raw(self) -> str: ...
    @property
    def company_name(self) -> str: ...
    @property
    def locations(self) -> tuple[Location, ...]: ...
    @property
    def compensation(self) -> Compensation: ...
    @property
    def visa_sponsorship(self) -> VisaStatus: ...
    @property
    def url(self) -> str: ...
    @property
    def first_seen_at_raw(self) -> str: ...


def sheet_for_posting(
    posting: PostingLike, description: str | None, *, applied_on: date | None
) -> OfferSheet:
    return OfferSheet(
        title=posting.title_raw,
        company=posting.company_name,
        description=description or "",
        locations=tuple(dict.fromkeys(filter(None, map(location_label, posting.locations)))),
        compensation=compensation_label(posting.compensation),
        visa=visa_label(posting.visa_sponsorship),
        url=posting.url,
        seen_on=date.fromisoformat(posting.first_seen_at_raw[:10]),
        applied_on=applied_on,
    )


def location_label(location: Location) -> str:
    # The region only stands in for a missing city: on its own it is often a macro-region code.
    place = location.city or location.region
    parts = [p for p in (place, location.country) if p]
    label = ", ".join(dict.fromkeys(parts)) or (location.raw or "")
    remote = location.remote_mode.value
    return f"{label} ({remote})" if label and remote in {"remote", "hybrid"} else label


def _amount(value: Decimal) -> str:
    return f"{value:,.0f}" if value == value.to_integral_value() else f"{value:,.2f}"


def compensation_label(compensation: Compensation) -> str | None:
    low, high = compensation.amount_min, compensation.amount_max
    if low is None and high is None:
        return compensation.raw
    span = " – ".join(_amount(v) for v in dict.fromkeys(v for v in (low, high) if v is not None))
    period = _PERIODS.get(compensation.period, "") if compensation.period else ""
    extras = [w for w, on in (("bonus", compensation.bonus_mentioned),
                              ("equity", compensation.equity_mentioned)) if on]  # fmt: skip
    text = " ".join(p for p in (compensation.currency or "", span, period) if p)
    return f"{text} + {' + '.join(extras)}" if extras else text


def visa_label(visa: VisaStatus) -> str | None:
    return _VISA.get(visa)


def _description_html(text: str) -> str:
    """Paragraphs, bullet lists and short headings, recovered from plain text."""
    out: list[str] = []
    items: list[str] = []

    def flush() -> None:
        if items:
            out.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()

    for block in re.split(r"\n\s*\n", text.strip()):
        for line in (ln.strip() for ln in block.splitlines()):
            if not line:
                continue
            if _BULLET.match(line):
                items.append(html.escape(_BULLET.sub("", line)))
                continue
            flush()
            tag = "h3" if _HEADING.match(line) else "p"
            out.append(f"<{tag}>{html.escape(line)}</{tag}>")
        flush()
    return "\n".join(out)


_STYLE = """
@page { size: A4; margin: 18mm 18mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Inter", "Helvetica Neue", "Liberation Sans", Arial, sans-serif;
       color: #1d2330; font-size: 10.2pt; line-height: 1.5; margin: 0; }
header { border-bottom: 2px solid #0b5394; padding-bottom: 10px; margin-bottom: 14px; }
.company { text-transform: uppercase; letter-spacing: .08em; font-size: 9pt; color: #0b5394;
           font-weight: 700; }
h1 { font-size: 19pt; line-height: 1.2; margin: 4px 0 10px; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: 3px 14px; margin: 0;
     font-size: 9.2pt; }
dt { color: #6a7385; } dd { margin: 0; }
a { color: #0b5394; word-break: break-all; }
main h3 { font-size: 10.5pt; margin: 14px 0 4px; color: #0b5394; }
main p { margin: 0 0 7px; } main ul { margin: 0 0 8px; padding-left: 18px; }
main li { margin: 0 0 3px; }
footer { margin-top: 18px; padding-top: 6px; border-top: 1px solid #d5dae3; color: #6a7385;
         font-size: 8pt; }
"""


def offer_html(sheet: OfferSheet, *, archived_on: date) -> str:
    rows: list[tuple[str, str]] = []
    if sheet.locations:
        rows.append(("Location", " · ".join(html.escape(loc) for loc in sheet.locations)))
    if sheet.compensation:
        rows.append(("Compensation", html.escape(sheet.compensation)))
    if sheet.visa:
        rows.append(("Visa", html.escape(sheet.visa)))
    rows += [(html.escape(k), html.escape(v)) for k, v in sheet.extra.items()]
    if sheet.seen_on:
        rows.append(("Seen", sheet.seen_on.isoformat()))
    if sheet.applied_on:
        rows.append(("Applied", sheet.applied_on.isoformat()))
    if sheet.url:
        link = html.escape(sheet.url, quote=True)
        rows.append(("Link", f'<a href="{link}">{link}</a>'))
    meta = "".join(f"<dt>{k}</dt><dd>{v}</dd>" for k, v in rows)
    title = html.escape(sheet.title)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title} — {html.escape(sheet.company)}</title>
<style>{_STYLE}</style></head>
<body>
<header><div class="company">{html.escape(sheet.company)}</div><h1>{title}</h1>
<dl>{meta}</dl></header>
<main>{_description_html(sheet.description) or "<p><em>No description.</em></p>"}</main>
<footer>Archived by JobTracker on {archived_on.isoformat()}.</footer>
</body></html>
"""


def html_to_pdf(page_html: str) -> bytes:
    """Print `page_html` to an A4 PDF with headless Chromium. Nothing is fetched: any request
    the page would make is aborted. Raises `RenderError` when no browser is available."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RenderError(
            "no headless browser — `uv sync --extra browser`, then `just browser-install`"
        ) from exc
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.route("**/*", lambda route: route.abort())
                page.set_content(page_html, wait_until="load")
                return bytes(
                    page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
                )
            finally:
                browser.close()
    except PlaywrightError as exc:
        raise RenderError(f"Chromium failed to print the offer: {exc}") from exc


def write_pdf(pdf: bytes, target: Path) -> None:
    """Write next to the target then rename: a crash never leaves half a PDF behind."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".pdf.part")
    partial.write_bytes(pdf)
    os.replace(partial, target)


def write_offer_pdf(sheet: OfferSheet, target: Path, *, archived_on: date) -> None:
    """Render `sheet` and write it to `target`. Raises `RenderError`."""
    write_pdf(html_to_pdf(offer_html(sheet, archived_on=archived_on)), target)
