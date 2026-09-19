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


# Real sentences from live postings the rules used to get wrong (found by the LLM re-read).
def test_between_x_and_y_is_a_range() -> None:
    c = parse_compensation(
        "The base salary range for this role is between $150,000 and $350,000.", country=None
    )
    assert (c.amount_min, c.amount_max) == (Decimal("150000"), Decimal("350000"))
    assert c.period == SalaryPeriod.YEAR


def test_and_without_between_is_not_a_range() -> None:
    c = parse_compensation("A salary of $150,000 and a $20,000 bonus", country=None)
    assert (c.amount_min, c.amount_max) == (Decimal("150000"), Decimal("150000"))


def test_a_weekly_figure_is_not_reported_as_a_yearly_one() -> None:
    c = parse_compensation("Anticipated weekly base salary range $3,500-$4,200.", country=None)
    assert (c.amount_min, c.amount_max, c.period) == (None, None, None)
    assert c.raw is not None  # what was seen is still kept


def test_per_week_is_weekly_too() -> None:
    c = parse_compensation("Pay is $900 per week.", country=None)
    assert c.amount_min is None


# Found by the LLM re-read: 75 of 353 stored "yearly" salaries were under $10k.
def test_a_company_size_is_not_a_salary() -> None:
    c = parse_compensation(
        "We manage $14.6 billion in assets. "
        "The base salary range for this role is $145,000-$175,000.",
        country=None,
    )
    assert (c.amount_min, c.amount_max) == (Decimal("145000"), Decimal("175000"))


def test_a_million_or_billion_alone_yields_nothing() -> None:
    c = parse_compensation("A firm with $2 billion under management.", country=None)
    assert c.amount_min is None


def test_the_figure_next_to_a_pay_word_beats_an_earlier_unrelated_one() -> None:
    c = parse_compensation(
        "Our $5,000 relocation package is generous. Base salary: $140,000 per year.", country=None
    )
    assert c.amount_min == Decimal("140000")


def test_labelled_minimum_and_maximum_make_a_range() -> None:
    c = parse_compensation(
        "Salary / Rate Minimum/yr: $150,000\nSalary / Rate Maximum/yr: $165,000", country=None
    )
    assert (c.amount_min, c.amount_max, c.currency, c.period) == (
        Decimal("150000"),
        Decimal("165000"),
        "USD",
        SalaryPeriod.YEAR,
    )


def test_a_small_figure_with_no_stated_period_is_not_called_yearly() -> None:
    c = parse_compensation("The hourly-ish rate is €14 - €16 for working students.", country=None)
    assert c.amount_min is None or c.period != SalaryPeriod.YEAR


def test_a_small_figure_without_any_period_word_is_dropped() -> None:
    c = parse_compensation("Pay: €2,000 for the placement.", country=None)
    assert c.amount_min is None
    assert c.raw is not None


def test_a_four_digit_amount_is_read_whole() -> None:
    c = parse_compensation("Base salary: €4500 per month.", country=None)
    assert (c.amount_min, c.period) == (Decimal("4500"), SalaryPeriod.MONTH)


def test_a_perk_is_not_a_salary() -> None:
    c = parse_compensation(
        "A learning budget of €1000 per year and a $5,000 relocation allowance.", country=None
    )
    assert c.amount_min is None


def test_the_k_of_a_range_belongs_to_both_ends() -> None:
    c = parse_compensation(
        "Annual compensation range $100-200K base plus profit share", country=None
    )
    assert (c.amount_min, c.amount_max) == (Decimal("100000"), Decimal("200000"))


def test_a_trading_volume_is_not_a_salary() -> None:
    """The line that gave a golden-corpus posting a phantom "salary disclosed" bonus."""
    c = parse_compensation(
        "Across all products, we have turned over >$1T in volumes since inception.", country=None
    )
    assert c.amount_min is None
