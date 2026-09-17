"""Salary ranges, currencies and periods — blueprint/wp/WP03-normalize.md §3.

`Decimal` end to end, never `float` (interdit n°11): a binary float cannot
represent a salary exactly, and this value is compared and sorted, not just
displayed. No currency conversion, ever (interdit n°5) — `country` is only
used to disambiguate an ambiguous "$" symbol.
"""

import re
from decimal import Decimal, InvalidOperation

from jobtracker.core.enums import SalaryPeriod
from jobtracker.core.models import Compensation

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

_PERIOD_PATTERNS: tuple[tuple[re.Pattern[str], SalaryPeriod], ...] = (
    (re.compile(r"per\s*month|/\s*month|monthly|per\s*mo\b", re.IGNORECASE), SalaryPeriod.MONTH),
    (re.compile(r"per\s*day|/\s*day|daily|per\s*diem", re.IGNORECASE), SalaryPeriod.DAY),
    (re.compile(r"per\s*hour|/\s*h(?:ou)?r|hourly", re.IGNORECASE), SalaryPeriod.HOUR),
    (
        re.compile(r"per\s*(?:year|annum)|/\s*year|annually|per\s*yr\b", re.IGNORECASE),
        SalaryPeriod.YEAR,
    ),
)

_NUMBER = r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?"
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
_UP_TO_RE = re.compile(r"\bup\s*to\b", re.IGNORECASE)


def _parse_amount(number: str, mult: str | None) -> Decimal | None:
    # European style ("4.500") uses '.' as a thousands separator when there
    # are exactly 3 digits after it and no other separator in play; US/UK
    # style ("4,500.50") uses ',' for thousands and '.' for decimals.
    cleaned = number
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "")
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+", cleaned):
        cleaned = cleaned.replace(",", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if mult and mult.lower() == "k":
        amount *= 1000
    elif mult and mult.lower() == "m":
        amount *= 1_000_000
    return amount


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


def _detect_period(text: str) -> SalaryPeriod | None:
    for pattern, period in _PERIOD_PATTERNS:
        if pattern.search(text):
            return period
    return None


def parse_compensation(description: str, *, country: str | None) -> Compensation:
    """Never raises (invariant I1) — an unparseable mention yields an empty `Compensation`."""
    bonus_mentioned = bool(_BONUS_RE.search(description))
    equity_mentioned = bool(_EQUITY_RE.search(description))

    match = _ANCHORED_AMOUNT_RE.search(description)
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
    first_amount = _parse_amount(number, mult)

    window_end = match.end()
    amount_min: Decimal | None
    amount_max: Decimal | None

    join_match = _RANGE_JOIN_RE.match(description, match.end())
    second_match = _PLAIN_AMOUNT_RE.match(description, join_match.end()) if join_match else None
    if second_match is not None:
        second_amount = _parse_amount(second_match.group("num"), second_match.group("mult") or mult)
        window_end = second_match.end()
        if _UP_TO_RE.search(description[max(0, match.start() - 15) : match.start()]):
            amount_min, amount_max = None, second_amount
        else:
            amount_min, amount_max = first_amount, second_amount
    elif _UP_TO_RE.search(description[max(0, match.start() - 15) : match.start()]):
        amount_min, amount_max = None, first_amount
    else:
        amount_min = amount_max = first_amount

    period = _detect_period(description[max(0, match.start() - 20) : window_end + 60])
    if period is None and (amount_min is not None or amount_max is not None):
        period = SalaryPeriod.YEAR

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
