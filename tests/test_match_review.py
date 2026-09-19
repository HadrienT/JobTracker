"""`match.review` — the whole-feed LLM re-read, as a pure decision.

The point of every test here is the same: what the model says is applied only when the text
backs it. A quote that is not in the posting, a figure that is not in its quote, a confidence
too low to overrule the rules — each is refused, and the refusal is recorded, never silent.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from factories_store import make_posting
from jobtracker.core.enums import (
    RemoteMode,
    ReviewOutcome,
    RoleFamily,
    SalaryPeriod,
    Seniority,
    VisaStatus,
)
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import Compensation, Location
from jobtracker.match.profile import Profile, build_profile
from jobtracker.match.review import ReviewOutput, ReviewPlan, ReviewSources, plan_review
from test_runtime_pipeline import _PROFILE_DATA

_DESCRIPTION = (
    "We are hiring a Quantitative Developer for our London desk. "
    "The base salary range for this role is £120,000 - £160,000 per year. "
    "You will need at least 3 years of experience in C++. "
    "We are unable to sponsor visas for this position. "
    "Applications close on 2027-03-31."
)
_SOURCES = ReviewSources(
    title="Quantitative Developer", location="London; New York", description=_DESCRIPTION
)


@pytest.fixture
def profile() -> Profile:
    return build_profile(_PROFILE_DATA)


def _output(**overrides: object) -> ReviewOutput:
    base: dict[str, object] = {
        "compensation": {
            "amount_min": None,
            "amount_max": None,
            "currency": None,
            "period": None,
            "evidence": None,
        },
        "locations": [],
        "seniority": "unknown",
        "min_years": None,
        "seniority_evidence": None,
        "visa_sponsorship": "unknown",
        "visa_evidence": None,
        "phd_required": False,
        "phd_evidence": None,
        "closes_at": None,
        "closes_evidence": None,
        "confidence": 0.95,
    }
    base.update(overrides)
    return ReviewOutput.model_validate(base)


def _salary(**overrides: object) -> dict[str, object]:
    comp: dict[str, object] = {
        "amount_min": "120000",
        "amount_max": "160000",
        "currency": "GBP",
        "period": "year",
        "evidence": "The base salary range for this role is £120,000 - £160,000 per year",
    }
    comp.update(overrides)
    return comp


def _posting(**overrides: object):
    base: dict[str, object] = {
        "role_family": RoleFamily.QUANT_DEV,
        "locations": (
            Location(
                city="London",
                country="GB",
                region="emea",
                remote_mode=RemoteMode.UNKNOWN,
                raw="London; New York",
            ),
        ),
    }
    base.update(overrides)
    return make_posting(**base)


def _plan(posting, output, profile: Profile, geo: GeoIndex, sources=_SOURCES) -> ReviewPlan:
    return plan_review(posting, output, sources=sources, profile=profile, geo=geo)


def _fields(plan: ReviewPlan) -> set[str]:
    return {c.field for c in plan.corrections}


# --- compensation ---------------------------------------------------------------------------


def test_a_salary_the_text_states_is_filled_in(profile: Profile, geo_index: GeoIndex) -> None:
    plan = _plan(_posting(), _output(compensation=_salary()), profile, geo_index)

    assert plan.outcome is ReviewOutcome.CORRECTED
    comp = plan.posting.compensation
    assert (comp.amount_min, comp.amount_max, comp.currency, comp.period) == (
        Decimal("120000"),
        Decimal("160000"),
        "GBP",
        SalaryPeriod.YEAR,
    )
    (correction,) = plan.corrections
    assert correction.field == "compensation"
    assert correction.before["amount_min"] is None
    assert correction.after["amount_min"] == "120000"
    assert "£120,000" in (correction.evidence or "")


def test_a_hallucinated_figure_has_no_quote_to_hide_behind(
    profile: Profile, geo_index: GeoIndex
) -> None:
    invented = _salary(
        amount_min="150000",
        amount_max="200000",
        evidence="The base salary range for this role is £150,000 - £200,000 per year",
    )

    plan = _plan(_posting(), _output(compensation=invented), profile, geo_index)

    assert plan.corrections == ()
    assert plan.outcome is ReviewOutcome.CONFIRMED
    assert any("not in the posting" in reason for reason in plan.refused)


def test_a_real_quote_cannot_carry_a_figure_it_does_not_contain(
    profile: Profile, geo_index: GeoIndex
) -> None:
    plan = _plan(_posting(), _output(compensation=_salary(amount_max="190000")), profile, geo_index)

    assert plan.corrections == ()
    assert any("190000" in reason and "own quote" in reason for reason in plan.refused)


@pytest.mark.parametrize(
    "bad",
    [
        {"currency": "XXX"},  # not a currency this feed knows
        {"currency": None},
        {"period": None},
        {"amount_min": "not-a-number"},
        {"amount_min": "160000", "amount_max": "120000"},  # inverted range
    ],
)
def test_a_malformed_salary_is_refused(
    bad: dict[str, object], profile: Profile, geo_index: GeoIndex
) -> None:
    quote = "The base salary range for this role is £120,000 - £160,000 per year"
    plan = _plan(
        _posting(), _output(compensation=_salary(evidence=quote, **bad)), profile, geo_index
    )

    assert plan.corrections == ()
    assert plan.refused


def test_an_implausible_amount_for_its_period_is_refused(
    profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(
        title="Quant", location=None, description="Pay is $120 per year for this internship."
    )
    plan = _plan(
        _posting(),
        _output(
            compensation=_salary(
                amount_min="120", amount_max=None, currency="USD", evidence="Pay is $120 per year"
            )
        ),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.corrections == ()
    assert any("implausible" in reason for reason in plan.refused)


def test_a_figure_the_rules_already_found_is_left_alone(
    profile: Profile, geo_index: GeoIndex
) -> None:
    posting = _posting(
        compensation=Compensation(
            amount_min=Decimal("120000"),
            amount_max=Decimal("160000"),
            currency="GBP",
            period=SalaryPeriod.YEAR,
            bonus_mentioned=False,
            equity_mentioned=False,
            raw=None,
        )
    )

    plan = _plan(posting, _output(compensation=_salary()), profile, geo_index)

    assert plan.outcome is ReviewOutcome.CONFIRMED
    assert plan.corrections == ()


def test_replacing_the_rules_figure_needs_the_higher_confidence(
    profile: Profile, geo_index: GeoIndex
) -> None:
    posting = _posting(
        compensation=Compensation(
            amount_min=Decimal("120000"),
            amount_max=Decimal("120000"),
            currency="GBP",
            period=SalaryPeriod.YEAR,
            bonus_mentioned=True,
            equity_mentioned=False,
            raw="raw",
        )
    )

    unsure = _plan(posting, _output(compensation=_salary(), confidence=0.7), profile, geo_index)
    sure = _plan(posting, _output(compensation=_salary(), confidence=0.9), profile, geo_index)

    assert unsure.corrections == ()
    assert any("too low a confidence" in reason for reason in unsure.refused)
    assert sure.posting.compensation.amount_max == Decimal("160000")
    assert sure.posting.compensation.bonus_mentioned is True  # what the rules found survives
    assert sure.posting.compensation.raw == "raw"


# --- locations ------------------------------------------------------------------------------


def _location(
    city: str | None, country: str | None, mode: str, evidence: str | None
) -> dict[str, object]:
    return {"city": city, "country": country, "remote_mode": mode, "evidence": evidence}


def test_a_city_the_rules_missed_is_added(profile: Profile, geo_index: GeoIndex) -> None:
    plan = _plan(
        _posting(),
        _output(locations=[_location("New York", "US", "onsite", "London; New York")]),
        profile,
        geo_index,
    )

    assert {(loc.city, loc.country) for loc in plan.posting.locations} == {
        ("London", "GB"),
        ("New York", "US"),
    }
    assert _fields(plan) == {"locations"}


_HYBRID_SOURCES = ReviewSources(
    title="Quant", location="Hybrid: London; New York", description=_DESCRIPTION
)


def test_a_posting_with_no_located_city_takes_the_models_cities(
    profile: Profile, geo_index: GeoIndex
) -> None:
    unresolved = _posting(
        locations=(
            Location(city=None, country=None, region=None, remote_mode=RemoteMode.UNKNOWN, raw="x"),
        )
    )

    plan = _plan(
        unresolved,
        _output(
            locations=[
                _location("London", "GB", "hybrid", "Hybrid: London; New York"),
                _location("New York", "US", "hybrid", "Hybrid: London; New York"),
            ]
        ),
        profile,
        geo_index,
        sources=_HYBRID_SOURCES,
    )

    assert {(loc.city, loc.remote_mode) for loc in plan.posting.locations} == {
        ("London", RemoteMode.HYBRID),
        ("New York", RemoteMode.HYBRID),
    }


def test_a_missing_mode_is_read_but_no_city_is_ever_dropped(
    profile: Profile, geo_index: GeoIndex
) -> None:
    both = _posting(
        locations=(
            Location(
                city="London", country="GB", region="emea", remote_mode=RemoteMode.UNKNOWN, raw="r"
            ),
            Location(
                city="New York", country="US", region="amer", remote_mode=RemoteMode.ONSITE, raw="r"
            ),
        )
    )

    plan = _plan(
        both,
        _output(locations=[_location("London", "GB", "hybrid", "Hybrid: London; New York")]),
        profile,
        geo_index,
        sources=_HYBRID_SOURCES,
    )

    modes = {loc.city: loc.remote_mode for loc in plan.posting.locations}
    assert modes == {"London": RemoteMode.HYBRID, "New York": RemoteMode.ONSITE}


def test_a_city_that_is_not_in_the_quote_is_refused(profile: Profile, geo_index: GeoIndex) -> None:
    plan = _plan(
        _posting(),
        _output(locations=[_location("Paris", "FR", "onsite", "London; New York")]),
        profile,
        geo_index,
    )

    assert plan.corrections == ()
    assert any("does not contain 'Paris'" in reason for reason in plan.refused)


def test_a_city_in_the_wrong_country_is_refused(profile: Profile, geo_index: GeoIndex) -> None:
    plan = _plan(
        _posting(),
        _output(locations=[_location("New York", "GB", "onsite", "London; New York")]),
        profile,
        geo_index,
    )

    assert plan.corrections == ()


def test_a_city_the_referential_does_not_know_is_reported_not_invented(
    profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(
        title="Quant", location="Reykjavik", description="Join us in Reykjavik."
    )

    plan = _plan(
        _posting(),
        _output(locations=[_location("Reykjavik", "IS", "onsite", "Join us in Reykjavik")]),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.corrections == ()
    assert plan.unknown_cities == (("Reykjavik", "IS"),)


def test_the_homonym_is_resolved_by_the_country_the_model_gave(
    profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(
        title="Quant", location="London, Ontario", description="Ontario office."
    )
    empty = _posting(
        locations=(
            Location(city=None, country=None, region=None, remote_mode=RemoteMode.UNKNOWN, raw="x"),
        )
    )

    plan = _plan(
        empty,
        _output(locations=[_location("London", "CA", "onsite", "London, Ontario")]),
        profile,
        geo_index,
        sources=sources,
    )

    assert [(loc.city, loc.country) for loc in plan.posting.locations] == [("London", "CA")]


# --- classification -------------------------------------------------------------------------


def test_a_visa_the_text_states_fills_an_unknown(profile: Profile, geo_index: GeoIndex) -> None:
    plan = _plan(
        _posting(visa_sponsorship=VisaStatus.UNKNOWN),
        _output(
            visa_sponsorship="no",
            visa_evidence="We are unable to sponsor visas for this position",
            confidence=0.7,  # enough to fill a gap
        ),
        profile,
        geo_index,
    )

    assert plan.posting.visa_sponsorship is VisaStatus.NO
    assert plan.posting.visa_evidence == "We are unable to sponsor visas for this position"
    assert plan.posting.resolver_stage == "llm"


def test_a_visa_without_a_quote_is_refused(profile: Profile, geo_index: GeoIndex) -> None:
    plan = _plan(
        _posting(),
        _output(visa_sponsorship="sponsors", visa_evidence="We happily sponsor everybody"),
        profile,
        geo_index,
    )

    assert plan.posting.visa_sponsorship is VisaStatus.UNKNOWN
    assert plan.corrections == ()


def test_the_model_saying_unknown_never_erases_what_the_rules_found(
    profile: Profile, geo_index: GeoIndex
) -> None:
    known = _posting(visa_sponsorship=VisaStatus.SPONSORS, seniority=Seniority.JUNIOR, min_years=2)

    plan = _plan(
        known, _output(visa_sponsorship="unknown", seniority="unknown"), profile, geo_index
    )

    assert plan.outcome is ReviewOutcome.CONFIRMED
    assert plan.posting.visa_sponsorship is VisaStatus.SPONSORS
    assert plan.posting.seniority is Seniority.JUNIOR


def test_min_years_must_be_a_number_of_its_own_quote(profile: Profile, geo_index: GeoIndex) -> None:
    quote = "You will need at least 3 years of experience in C++"
    good = _plan(
        _posting(),
        _output(seniority="mid", min_years=3, seniority_evidence=quote),
        profile,
        geo_index,
    )
    wrong = _plan(
        _posting(),
        _output(seniority="mid", min_years=7, seniority_evidence=quote),
        profile,
        geo_index,
    )

    assert good.posting.min_years == 3
    assert good.posting.seniority is _posting().seniority  # years are not the word for a level
    assert wrong.posting.min_years is None
    assert any("not in its quote" in reason for reason in wrong.refused)


def test_overruling_a_rules_seniority_needs_the_higher_confidence(
    profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(
        title="Quant", location=None, description="We are looking for a senior developer."
    )
    quote = "We are looking for a senior developer"
    rules_said_junior = _posting(seniority=Seniority.JUNIOR)

    unsure = _plan(
        rules_said_junior,
        _output(seniority="senior", seniority_evidence=quote, confidence=0.7),
        profile,
        geo_index,
        sources=sources,
    )
    sure = _plan(
        rules_said_junior,
        _output(seniority="senior", seniority_evidence=quote, confidence=0.9),
        profile,
        geo_index,
        sources=sources,
    )

    assert unsure.posting.seniority is Seniority.JUNIOR
    assert sure.posting.seniority is Seniority.SENIOR


def test_a_level_needs_the_word_that_names_it(profile: Profile, geo_index: GeoIndex) -> None:
    """ "3+ years of experience" is a number; only "senior" says senior."""
    quote = "You will need at least 3 years of experience in C++"
    plan = _plan(
        _posting(seniority=Seniority.MID),
        _output(seniority="senior", seniority_evidence=quote, confidence=0.95),
        profile,
        geo_index,
    )

    assert plan.posting.seniority is Seniority.MID
    assert any("never names the level" in reason for reason in plan.refused)


def test_a_phd_requirement_is_only_ever_added_never_removed(
    profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(
        title="Quant", location=None, description="A PhD is required for this role."
    )
    added = _plan(
        _posting(phd_required=False),
        _output(phd_required=True, phd_evidence="A PhD is required for this role"),
        profile,
        geo_index,
        sources=sources,
    )
    removed = _plan(_posting(phd_required=True), _output(phd_required=False), profile, geo_index)

    assert added.posting.phd_required is True
    assert removed.posting.phd_required is True


def test_a_phd_quote_that_does_not_mention_a_phd_is_refused(
    profile: Profile, geo_index: GeoIndex
) -> None:
    plan = _plan(
        _posting(phd_required=False),
        _output(phd_required=True, phd_evidence="You will need at least 3 years of experience"),
        profile,
        geo_index,
    )

    assert plan.posting.phd_required is False


def test_the_role_family_is_not_the_reviews_to_change(
    profile: Profile, geo_index: GeoIndex
) -> None:
    """The title decides the family; a reading of the body must not reshuffle it."""
    assert "role_family" not in ReviewOutput.model_json_schema()["properties"]


# --- deadline, confidence, outcome ----------------------------------------------------------


def test_a_deadline_the_text_states_is_filled_in(profile: Profile, geo_index: GeoIndex) -> None:
    plan = _plan(
        _posting(closes_at=None),
        _output(closes_at="2027-03-31", closes_evidence="Applications close on 2027-03-31"),
        profile,
        geo_index,
    )

    assert plan.posting.closes_at == datetime(2027, 3, 31, tzinfo=UTC)


def test_a_deadline_before_the_posting_existed_is_refused(
    profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(
        title="Quant", location=None, description="Applications close on 2001-01-01."
    )
    plan = _plan(
        _posting(closes_at=None),
        _output(closes_at="2001-01-01", closes_evidence="Applications close on 2001-01-01"),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.posting.closes_at is None


def test_an_under_confident_reading_is_set_aside_whole(
    profile: Profile, geo_index: GeoIndex
) -> None:
    plan = _plan(_posting(), _output(compensation=_salary(), confidence=0.3), profile, geo_index)

    assert plan.outcome is ReviewOutcome.SET_ASIDE
    assert plan.corrections == ()
    assert plan.posting == _posting()


def test_a_non_conforming_reply_is_set_aside(profile: Profile, geo_index: GeoIndex) -> None:
    plan = _plan(_posting(), None, profile, geo_index)

    assert plan.outcome is ReviewOutcome.SET_ASIDE
    assert plan.confidence is None


def test_a_reading_that_changes_nothing_is_confirmed(profile: Profile, geo_index: GeoIndex) -> None:
    plan = _plan(_posting(), _output(), profile, geo_index)

    assert plan.outcome is ReviewOutcome.CONFIRMED
    assert plan.posting == _posting()


def test_one_bad_field_does_not_sink_the_good_ones(profile: Profile, geo_index: GeoIndex) -> None:
    plan = _plan(
        _posting(),
        _output(
            compensation=_salary(),
            visa_sponsorship="sponsors",
            visa_evidence="We sponsor everyone",  # not in the text
        ),
        profile,
        geo_index,
    )

    assert _fields(plan) == {"compensation"}
    assert any("visa_sponsorship" in reason for reason in plan.refused)


def test_the_check_ignores_case_and_punctuation_but_not_words(
    profile: Profile, geo_index: GeoIndex
) -> None:
    shouty = _salary(evidence="THE BASE SALARY RANGE FOR THIS ROLE IS £120,000 — £160,000 PER YEAR")
    plan = _plan(_posting(), _output(compensation=shouty), profile, geo_index)

    assert _fields(plan) == {"compensation"}


def test_today_is_not_an_input(profile: Profile, geo_index: GeoIndex) -> None:
    """The plan is a function of the reply and the posting alone — replayable offline."""
    once = _plan(_posting(), _output(compensation=_salary()), profile, geo_index)
    again = _plan(_posting(), _output(compensation=_salary()), profile, geo_index)

    assert once == again
    assert date.today().year >= 2026


# --- what the first live dry run taught ------------------------------------------------------


def test_a_weekly_figure_is_refused_not_stored_as_something_else(
    profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(
        title="Intern",
        location=None,
        description="Anticipated weekly base salary range $3,500-$4,200.",
    )
    plan = _plan(
        _posting(),
        _output(
            compensation=_salary(
                amount_min="3500",
                amount_max="4200",
                currency="USD",
                period="month",
                evidence="Anticipated weekly base salary range $3,500-$4,200.",
            )
        ),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.corrections == ()
    assert any("weekly" in reason for reason in plan.refused)


def test_a_period_the_quote_contradicts_is_refused(profile: Profile, geo_index: GeoIndex) -> None:
    sources = ReviewSources(
        title="Quant", location=None, description="Pay is $95 per hour, full time."
    )
    plan = _plan(
        _posting(),
        _output(
            compensation=_salary(
                amount_min="95",
                amount_max=None,
                currency="USD",
                period="year",
                evidence="Pay is $95 per hour",
            )
        ),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.corrections == ()
    assert any("says hour, not year" in reason for reason in plan.refused)


def test_a_quote_that_repeats_the_prompts_label_is_still_a_quote(
    profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(title="Quant", location="Paris", description="Join our Paris office.")
    empty = _posting(
        locations=(
            Location(city=None, country=None, region=None, remote_mode=RemoteMode.UNKNOWN, raw="x"),
        )
    )

    plan = _plan(
        empty,
        _output(locations=[_location("Paris", "FR", "onsite", "Location field: Paris")]),
        profile,
        geo_index,
        sources=sources,
    )

    assert [(loc.city, loc.country) for loc in plan.posting.locations] == [("Paris", "FR")]


def test_agreeing_with_the_rules_is_silent(profile: Profile, geo_index: GeoIndex) -> None:
    """No quote is demanded — and none refused — for a value that changes nothing."""
    posting = _posting(seniority=Seniority.GRADUATE, min_years=None)

    plan = _plan(
        posting, _output(seniority="graduate", seniority_evidence=None), profile, geo_index
    )

    assert plan.corrections == ()
    assert plan.refused == ()
    assert plan.outcome is ReviewOutcome.CONFIRMED


def test_a_mode_is_only_taken_from_a_quote_that_says_it(
    profile: Profile, geo_index: GeoIndex
) -> None:
    """A bare city name is not "on-site": inferring it would stamp every posting onsite."""
    plan = _plan(
        _posting(),
        _output(locations=[_location("New York", "US", "onsite", "London; New York")]),
        profile,
        geo_index,
    )

    added = next(loc for loc in plan.posting.locations if loc.city == "New York")
    assert added.remote_mode is RemoteMode.UNKNOWN


def test_a_phd_quote_must_state_a_requirement(profile: Profile, geo_index: GeoIndex) -> None:
    sources = ReviewSources(
        title="Intern", location=None, description="The PhD quant internship is a 10-week program."
    )
    plan = _plan(
        _posting(phd_required=False),
        _output(phd_required=True, phd_evidence="The PhD quant internship is a 10-week program"),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.posting.phd_required is False
    assert any("states no requirement" in reason for reason in plan.refused)


def test_no_visa_needs_an_exclusion_not_a_preference(profile: Profile, geo_index: GeoIndex) -> None:
    sources = ReviewSources(
        title="Quant",
        location=None,
        description="We encourage Singapore citizens to apply. We cannot sponsor visas.",
    )
    preference = _plan(
        _posting(),
        _output(visa_sponsorship="no", visa_evidence="We encourage Singapore citizens to apply"),
        profile,
        geo_index,
        sources=sources,
    )
    exclusion = _plan(
        _posting(),
        _output(visa_sponsorship="no", visa_evidence="We cannot sponsor visas"),
        profile,
        geo_index,
        sources=sources,
    )

    assert preference.posting.visa_sponsorship is VisaStatus.UNKNOWN
    assert exclusion.posting.visa_sponsorship is VisaStatus.NO


@pytest.mark.parametrize("minimum_only", [("145000", None), (None, "145000")])
def test_one_figure_spelt_differently_is_not_a_correction(
    minimum_only: tuple[str | None, str | None], profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(
        title="Quant", location=None, description="Base salary is $145,000 a year."
    )
    posting = _posting(
        compensation=Compensation(
            amount_min=Decimal("145000"),
            amount_max=Decimal("145000"),
            currency="USD",
            period=SalaryPeriod.YEAR,
            bonus_mentioned=False,
            equity_mentioned=False,
            raw=None,
        )
    )
    low, high = minimum_only

    plan = _plan(
        posting,
        _output(
            compensation=_salary(
                amount_min=low,
                amount_max=high,
                currency="USD",
                evidence="Base salary is $145,000 a year",
            )
        ),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.corrections == ()


@pytest.mark.parametrize(
    "quote",
    [
        "Application expected to close: 12/23/2026",
        "Apply by 23 December 2026",
        "Closing date: Dec 23, 2026",
    ],
)
def test_a_deadline_written_in_any_common_format_is_accepted(
    quote: str, profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(title="Quant", location=None, description=quote + ".")
    plan = _plan(
        _posting(closes_at=None),
        _output(closes_at="2026-12-23", closes_evidence=quote),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.posting.closes_at == datetime(2026, 12, 23, tzinfo=UTC)


def test_a_deadline_the_model_worked_out_itself_is_refused(
    profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(
        title="Quant", location=None, description="Applications close in three weeks from posting."
    )
    plan = _plan(
        _posting(closes_at=None),
        _output(closes_at="2026-12-23", closes_evidence="Applications close in three weeks"),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.posting.closes_at is None
    assert any("not written in its quote" in reason for reason in plan.refused)


# --- what the first full run taught (audit of 77 applied corrections) ------------------------


@pytest.mark.parametrize(
    "quote",
    [
        "Advanced degree (Master's or PhD) in Machine Learning, Statistics, Physics",
        "PhD or equivalent experience in a quantitative field",
        "A PhD degree in mathematics is preferred",
    ],
)
def test_a_phd_offered_as_one_option_or_a_plus_is_not_a_requirement(
    quote: str, profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(title="Quant", location=None, description=quote + ".")
    plan = _plan(
        _posting(phd_required=False),
        _output(phd_required=True, phd_evidence=quote),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.posting.phd_required is False
    assert any("one option" in reason for reason in plan.refused)


def test_a_salary_whose_quote_names_no_currency_is_refused(
    profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(
        title="Quant",
        location=None,
        description="Base pay is expected to be between 150,000 and 180,000.",
    )
    plan = _plan(
        _posting(),
        _output(
            compensation=_salary(
                amount_min="150000",
                amount_max="180000",
                currency="USD",
                evidence="Base pay is expected to be between 150,000 and 180,000",
            )
        ),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.corrections == ()
    assert any("does not mention USD" in reason for reason in plan.refused)


def test_a_symbol_or_a_code_in_the_quote_names_the_currency(
    profile: Profile, geo_index: GeoIndex
) -> None:
    for text, code in [
        ("Base pay: $150,000-$180,000", "USD"),
        ("Base pay: 150,000-180,000 USD", "USD"),
    ]:
        sources = ReviewSources(title="Quant", location=None, description=text + " a year.")
        plan = _plan(
            _posting(),
            _output(
                compensation=_salary(
                    amount_min="150000", amount_max="180000", currency=code, evidence=text
                )
            ),
            profile,
            geo_index,
            sources=sources,
        )
        assert _fields(plan) == {"compensation"}, text


@pytest.mark.parametrize("place", ["Virtual", "Anywhere"])
def test_remote_is_not_read_into_a_word_that_does_not_say_it(
    place: str, profile: Profile, geo_index: GeoIndex
) -> None:
    sources = ReviewSources(title="Talent community", location=place, description="Join us.")
    empty = _posting(
        locations=(
            Location(
                city=None, country=None, region=None, remote_mode=RemoteMode.UNKNOWN, raw=place
            ),
        )
    )

    plan = _plan(
        empty,
        _output(locations=[_location(None, None, "remote", place)]),
        profile,
        geo_index,
        sources=sources,
    )

    assert plan.corrections == ()
