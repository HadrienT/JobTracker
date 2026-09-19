"""Money as a value that never converts silently — blueprint/09-CONVENTIONS.md rule N2/N3.

Interdit n°5 (blueprint/00-PRIMER.md §2): a range never gets converted at
write time. Conversion exists only for display, and it carries its rate and
its date.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, field_validator

from jobtracker.core.enums import SalaryPeriod


class Money(BaseModel, frozen=True):
    """An amount tied to its currency. Cross-currency arithmetic is a TypeError."""

    amount: Decimal
    currency: str  # ISO-4217, uppercase

    @field_validator("currency")
    @classmethod
    def _currency_upper(cls, value: str) -> str:
        if len(value) != 3 or not value.isalpha():
            raise ValueError(f"currency must be a 3-letter ISO-4217 code, got {value!r}")
        return value.upper()

    def __add__(self, other: Any) -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        if other.currency != self.currency:
            raise TypeError(
                f"cannot add {self.currency} and {other.currency} "
                "without an explicit, dated conversion"
            )
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        if other.currency != self.currency:
            raise TypeError(
                f"cannot compare {self.currency} and {other.currency} "
                "without an explicit, dated conversion"
            )
        return self.amount < other.amount


def parse_amount(number: str, mult: str | None) -> Decimal | None:
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


_ANY_AMOUNT_RE = re.compile(r"(?<![\w.])(?P<num>\d[\d.,]*)\s*(?P<mult>[kKmM])?(?![\w])")


def amounts_in(text: str) -> frozenset[Decimal]:
    """Every number in `text`, "175k" and "1.2m" expanded: what an amount quoted from it can be.

    Used to check that a figure someone else (the LLM) extracted is *in* the text it claims to
    have read it from. Deliberately generous — a year or a phone number is in the set too — since
    the question is only "could this figure have come from this quote", never "is it a salary".
    """
    found: set[Decimal] = set()
    for match in _ANY_AMOUNT_RE.finditer(text):
        amount = parse_amount(match.group("num").rstrip(".,"), match.group("mult"))
        if amount is not None:
            found.add(amount)
    return frozenset(found)


_PERIOD_PATTERNS: tuple[tuple[re.Pattern[str], SalaryPeriod], ...] = (
    (re.compile(r"per\s*month|/\s*month|monthly|per\s*mo\b", re.IGNORECASE), SalaryPeriod.MONTH),
    (re.compile(r"per\s*day|/\s*day|daily|per\s*diem", re.IGNORECASE), SalaryPeriod.DAY),
    (re.compile(r"per\s*hour|/\s*h(?:ou)?r|hourly", re.IGNORECASE), SalaryPeriod.HOUR),
    (
        re.compile(
            r"per\s*(?:year|annum)|/\s*(?:year|yr)\b|annually|per\s*yr\b|a year", re.IGNORECASE
        ),
        SalaryPeriod.YEAR,
    ),
)


# The feed stores year/month/day/hour: a weekly figure fits none, and calling it a yearly one
# ("$3,500-$4,200" a year) is worse than showing nothing.
_WEEKLY_RE = re.compile(r"\bweekly\b|per\s*week|/\s*week", re.IGNORECASE)


def is_weekly(text: str) -> bool:
    """True when `text` prices something per week — a period the feed has no column for."""
    return _WEEKLY_RE.search(text) is not None


def detect_period(text: str) -> SalaryPeriod | None:
    for pattern, period in _PERIOD_PATTERNS:
        if pattern.search(text):
            return period
    return None
