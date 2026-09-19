"""Salary ranges, currencies and periods — blueprint/wp/WP03-normalize.md §3.

`Decimal` end to end, never `float` (interdit n°11): a binary float cannot
represent a salary exactly, and this value is compared and sorted, not just
displayed. No currency conversion, ever (interdit n°5) — `country` is only
used to disambiguate an ambiguous "$" symbol.
"""

import re
from decimal import Decimal

from jobtracker.core.enums import SalaryPeriod
from jobtracker.core.models import Compensation
from jobtracker.core.money import detect_period, is_weekly, parse_amount

_PLACEHOLDER_RE = re.compile(
    r"\b(?:competitive|doe|negotiable|dependent on experience|market rate)\b", re.IGNORECASE
)
_BONUS_RE = re.compile(r"\bbonus(?:es)?\b", re.IGNORECASE)
_EQUITY_RE = re.compile(r"\bequity\b|\bstock options?\b|\bRSUs?\b", re.IGNORECASE)

_CURRENCY_SYMBOLS = {"£": "GBP", "€": "EUR", "$": "USD", "¥": "JPY"}
_CURRENCY_WORDS = {
    "gbp": "GBP",
    "usd": "USD",
    "eur": "EUR",
    "chf": "CHF",
    "sgd": "SGD",
    "hkd": "HKD",
}
_DOLLAR_COUNTRY_CURRENCY = {
    "CA": "CAD",
    "AU": "AUD",
    "SG": "SGD",
    "HK": "HKD",
    "NZ": "NZD",
}

_NUMBER = r"\d+(?:[.,]\d{3})*(?:[.,]\d+)?"
# An amount must carry a currency mark — symbol before, or ISO code after —
# or it is just some other number in the text ("2027 Start", a percentage).
_ANCHORED_AMOUNT_RE = re.compile(
    rf"(?:(?P<symbol>[£€$¥])\s*(?P<num1>{_NUMBER})\s*(?P<mult1>[kKmM])?)"
    rf"|(?:(?P<num2>{_NUMBER})\s*(?P<mult2>[kKmM])?\s*(?P<currency_word>GBP|USD|EUR|CHF|SGD|HKD)\b)",
)
# The second half of a range inherits the first amount's currency mark, but
# may repeat it too ("£65,000 - £85,000") — accepted and ignored here.
_PLAIN_AMOUNT_RE = re.compile(rf"[£€$¥]?\s*(?P<num>{_NUMBER})\s*(?P<mult>[kKmM])?")
_RANGE_JOIN_RE = re.compile(r"\s*(?:-|–|—|to)\s*")
# A figure followed by one of these is the size of a company or a fund, not a pay: "$14.6 billion
# in assets" was once stored as a yearly salary of 14.6 dollars.
_SCALE_WORD_RE = re.compile(r"\s*(?:billion|million|trillion|bn|mm)\b", re.IGNORECASE)
# An amount right after one of these is a perk or a one-off, not the pay: "a learning budget of
# €1000 per year", "a $5,000 relocation allowance", "a sign-on bonus of $20,000".
_NOT_PAY_RE = re.compile(
    r"budget|allowance|stipend|relocation|reimburs|voucher|sign[- ]?on|bonus of|up to a\s*$",
    re.IGNORECASE,
)
_NOT_PAY_AFTER_RE = re.compile(
    r"\s*(?:relocation|sign[- ]?on|signing|stipend|allowance|voucher|budget|bonus)", re.IGNORECASE
)
_PAY_CUE_RE = re.compile(
    r"salary|compensation|base pay|pay range|pay rate|rate of pay|remuneration|per annum|"
    r"annual|a year|per year|/\s*yr|hourly|per hour|base rate|wage",
    re.IGNORECASE,
)
# "Salary / Rate Minimum/yr: $150,000 Salary / Rate Maximum/yr: $165,000": two labelled figures.
_LABELLED_RANGE_RE = re.compile(
    r"minimum[^\d$£€]{0,25}(?P<sym>[£€$¥])?\s*(?P<lo>\d[\d.,]*)"
    r"[\s\S]{0,60}?maximum[^\d$£€]{0,25}[£€$¥]?\s*(?P<hi>\d[\d.,]*)",
    re.IGNORECASE,
)
# A year figure below this is a monthly, weekly or hourly one whose period went unstated: showing
# it as "per year" would be a lie, so it is dropped (the raw text is kept).
_MIN_PLAUSIBLE_YEARLY = Decimal(10_000)
_UP_TO_RE = re.compile(r"\bup\s*to\b", re.IGNORECASE)
# "between $150,000 and $350,000": "and" joins a range only after "between" — "$150,000 and a
# $20,000 bonus" is two different things.
_BETWEEN_RE = re.compile(r"\bbetween\s*$", re.IGNORECASE)
_AND_JOIN_RE = re.compile(r"\s*and\s*", re.IGNORECASE)


def _detect_currency(
    symbol: str | None, currency_word: str | None, country: str | None
) -> str | None:
    if currency_word:
        return _CURRENCY_WORDS.get(currency_word.lower(), currency_word.upper())
    if symbol == "$":
        return _DOLLAR_COUNTRY_CURRENCY.get((country or "").upper(), "USD")
    if symbol:
        return _CURRENCY_SYMBOLS.get(symbol)
    return None


def _pick_amount(description: str) -> re.Match[str] | None:
    """The anchored amount that is a pay: not a company size, preferably next to a pay word."""
    candidates = [
        m
        for m in _ANCHORED_AMOUNT_RE.finditer(description)
        if _SCALE_WORD_RE.match(description, m.end()) is None
        and _NOT_PAY_RE.search(description[max(0, m.start() - 25) : m.start()]) is None
        and _NOT_PAY_AFTER_RE.match(description, m.end()) is None
    ]
    for candidate in candidates:
        # A pay word just before the figure, or just after it: further away it describes
        # another sentence ("a $5,000 relocation package ... Base salary: $140,000").
        around = description[max(0, candidate.start() - 60) : candidate.end() + 25]
        if _PAY_CUE_RE.search(around):
            return candidate
    return candidates[0] if candidates else None


def _parse_labelled_range(description: str, country: str | None) -> Compensation | None:
    match = _LABELLED_RANGE_RE.search(description)
    if match is None:
        return None
    low = parse_amount(match.group("lo").rstrip(".,"), None)
    high = parse_amount(match.group("hi").rstrip(".,"), None)
    if low is None or high is None or low > high:
        return None
    context = description[max(0, match.start() - 20) : match.end() + 20]
    period = detect_period(context) or (
        SalaryPeriod.YEAR if high >= _MIN_PLAUSIBLE_YEARLY else None
    )
    if period is None or is_weekly(context):
        return None
    return Compensation(
        amount_min=low,
        amount_max=high,
        currency=_detect_currency(match.group("sym"), None, country),
        period=period,
        bonus_mentioned=False,
        equity_mentioned=False,
        raw=description[match.start() : match.end()].strip(),
    )


def parse_compensation(description: str, *, country: str | None) -> Compensation:
    """Never raises (invariant I1) — an unparseable mention yields an empty `Compensation`."""
    bonus_mentioned = bool(_BONUS_RE.search(description))
    equity_mentioned = bool(_EQUITY_RE.search(description))

    labelled = _parse_labelled_range(description, country)
    if labelled is not None:
        return labelled.model_copy(
            update={"bonus_mentioned": bonus_mentioned, "equity_mentioned": equity_mentioned}
        )

    match = _pick_amount(description)
    if match is None:
        placeholder = _PLACEHOLDER_RE.search(description)
        raw = placeholder.group(0) if placeholder else None
        return Compensation(
            amount_min=None,
            amount_max=None,
            currency=None,
            period=None,
            bonus_mentioned=bonus_mentioned,
            equity_mentioned=equity_mentioned,
            raw=raw,
        )

    number = match.group("num1") or match.group("num2")
    mult = match.group("mult1") or match.group("mult2")
    currency = _detect_currency(match.group("symbol"), match.group("currency_word"), country)
    first_amount = parse_amount(number, mult)

    window_end = match.end()
    amount_min: Decimal | None
    amount_max: Decimal | None

    join_match = _RANGE_JOIN_RE.match(description, match.end())
    if join_match is None and _BETWEEN_RE.search(
        description[max(0, match.start() - 12) : match.start()]
    ):
        join_match = _AND_JOIN_RE.match(description, match.end())
    second_match = _PLAIN_AMOUNT_RE.match(description, join_match.end()) if join_match else None
    if second_match is not None:
        second_amount = parse_amount(second_match.group("num"), second_match.group("mult") or mult)
        if mult is None and second_match.group("mult") and first_amount is not None:
            # "$100-200K": the K belongs to both ends.
            first_amount = parse_amount(number, second_match.group("mult"))
        window_end = second_match.end()
        if _UP_TO_RE.search(description[max(0, match.start() - 15) : match.start()]):
            amount_min, amount_max = None, second_amount
        else:
            amount_min, amount_max = first_amount, second_amount
    elif _UP_TO_RE.search(description[max(0, match.start() - 15) : match.start()]):
        amount_min, amount_max = None, first_amount
    else:
        amount_min = amount_max = first_amount

    context = description[max(0, match.start() - 60) : window_end + 60]
    if is_weekly(context):
        return Compensation(
            amount_min=None,
            amount_max=None,
            currency=currency,
            period=None,
            bonus_mentioned=bonus_mentioned,
            equity_mentioned=equity_mentioned,
            raw=description[match.start() : window_end + 20].strip(),
        )
    period = detect_period(description[max(0, match.start() - 20) : window_end + 60])
    if period is None and (amount_min is not None or amount_max is not None):
        biggest = max(a for a in (amount_min, amount_max) if a is not None)
        if biggest >= _MIN_PLAUSIBLE_YEARLY:
            period = SalaryPeriod.YEAR
        else:
            # No period stated and too small to be a year: an hourly, monthly or weekly figure
            # we cannot name. Better nothing than a wrong "per year".
            return Compensation(
                amount_min=None,
                amount_max=None,
                currency=currency,
                period=None,
                bonus_mentioned=bonus_mentioned,
                equity_mentioned=equity_mentioned,
                raw=description[match.start() : window_end + 20].strip(),
            )

    raw = description[match.start() : window_end + 20].strip()

    return Compensation(
        amount_min=amount_min,
        amount_max=amount_max,
        currency=currency,
        period=period,
        bonus_mentioned=bonus_mentioned,
        equity_mentioned=equity_mentioned,
        raw=raw,
    )
