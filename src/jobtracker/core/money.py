"""Money as a value that never converts silently — blueprint/09-CONVENTIONS.md rule N2/N3.

Interdit n°5 (blueprint/00-PRIMER.md §2): a range never gets converted at
write time. Conversion exists only for display, and it carries its rate and
its date.
"""

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, field_validator


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
