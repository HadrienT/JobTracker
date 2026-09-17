from decimal import Decimal

import pytest

from jobtracker.core.money import Money


def test_add_same_currency() -> None:
    total = Money(amount=Decimal("10.50"), currency="usd") + Money(
        amount=Decimal("5"), currency="USD"
    )
    assert total.amount == Decimal("15.50")
    assert total.currency == "USD"


def test_add_cross_currency_raises_type_error() -> None:
    with pytest.raises(TypeError):
        Money(amount=Decimal("10"), currency="EUR") + Money(amount=Decimal("10"), currency="USD")


def test_compare_cross_currency_raises_type_error() -> None:
    with pytest.raises(TypeError):
        _ = Money(amount=Decimal("10"), currency="EUR") < Money(
            amount=Decimal("10"), currency="USD"
        )


def test_currency_is_normalized_to_uppercase() -> None:
    assert Money(amount=Decimal("1"), currency="gbp").currency == "GBP"


def test_invalid_currency_code_rejected() -> None:
    with pytest.raises(ValueError):
        Money(amount=Decimal("1"), currency="X")
