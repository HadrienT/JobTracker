from decimal import Decimal

from jobtracker.core.enums import SalaryPeriod
from jobtracker.normalize.compensation import parse_compensation


def test_gbp_range() -> None:
    c = parse_compensation("£65,000 - £85,000", country=None)
    assert c.amount_min == Decimal("65000")
    assert c.amount_max == Decimal("85000")
    assert c.currency == "GBP"
    assert c.period == SalaryPeriod.YEAR


def test_k_suffix_range_with_bonus() -> None:
    c = parse_compensation("$150K–$250K + bonus", country="US")
    assert c.amount_min == Decimal("150000")
    assert c.amount_max == Decimal("250000")
    assert c.currency == "USD"
    assert c.bonus_mentioned is True


def test_european_decimal_style_monthly() -> None:
    c = parse_compensation("€4.500 per month", country="NL")
    assert c.amount_min == Decimal("4500")
    assert c.currency == "EUR"
    assert c.period == SalaryPeriod.MONTH


def test_competitive_is_empty_but_keeps_raw() -> None:
    c = parse_compensation("Competitive", country=None)
    assert c.amount_min is None
    assert c.amount_max is None
    assert c.raw == "Competitive"


def test_up_to_has_no_minimum() -> None:
    c = parse_compensation("up to £90,000", country=None)
    assert c.amount_min is None
    assert c.amount_max == Decimal("90000")


def test_never_uses_float() -> None:
    c = parse_compensation("$100,000", country="US")
    assert isinstance(c.amount_min, Decimal)


def test_dollar_currency_follows_country_hint() -> None:
    c = parse_compensation("$120,000", country="CA")
    assert c.currency == "CAD"


def test_equity_mentioned() -> None:
    c = parse_compensation("Base salary plus equity and RSUs.", country=None)
    assert c.equity_mentioned is True
