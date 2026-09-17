from jobtracker.core.enums import Seniority
from jobtracker.normalize.seniority import parse_seniority
from jobtracker.normalize.taxonomy import Taxonomy


def test_explicit_years_win_over_a_contradicting_title(taxonomy: Taxonomy) -> None:
    # blueprint/wp/WP03-normalize.md §3: description outranks the title.
    seniority, years = parse_seniority(
        "Junior Developer", "You will need 5+ years of experience.", taxonomy=taxonomy
    )
    assert seniority == Seniority.SENIOR
    assert years == 5


def test_program_marker_gives_graduate(taxonomy: Taxonomy) -> None:
    # Programme/intern markers are read from the title, not the description
    # (normalize/seniority.py: the same "see our campus postings" disclaimer
    # sits in a company's boilerplate for roles that are *not* campus hires).
    seniority, years = parse_seniority(
        "Graduate Software Engineer", "Join our team in 2027.", taxonomy=taxonomy
    )
    assert seniority == Seniority.GRADUATE
    assert years is None


def test_title_marker_when_nothing_else_is_said(taxonomy: Taxonomy) -> None:
    seniority, years = parse_seniority("Senior Software Engineer", "", taxonomy=taxonomy)
    assert seniority == Seniority.SENIOR
    assert years is None


def test_nothing_said_is_unknown_not_zero(taxonomy: Taxonomy) -> None:
    seniority, years = parse_seniority("Executive Assistant", "A great role.", taxonomy=taxonomy)
    assert seniority == Seniority.UNKNOWN
    assert years is None


def test_company_track_record_years_are_not_a_requirement(taxonomy: Taxonomy) -> None:
    # "We have a 25+ year track record of innovation" is the company's age.
    seniority, years = parse_seniority(
        "Software Developer", "We have a 25+ year track record of innovation.", taxonomy=taxonomy
    )
    assert years is None
    assert seniority == Seniority.UNKNOWN


def test_french_years_phrasing(taxonomy: Taxonomy) -> None:
    seniority, years = parse_seniority(
        "Développeur", "Au moins 3 ans d'expérience requise.", taxonomy=taxonomy
    )
    assert years == 3
    assert seniority == Seniority.MID


def test_german_years_phrasing(taxonomy: Taxonomy) -> None:
    seniority, years = parse_seniority(
        "Legal Counsel", "Du hast mindestens 2 Jahre Berufserfahrung.", taxonomy=taxonomy
    )
    assert years == 2
    assert seniority == Seniority.JUNIOR


def test_campus_title_without_years_is_graduate(taxonomy: Taxonomy) -> None:
    seniority, years = parse_seniority("Campus Software Engineer", "", taxonomy=taxonomy)
    assert seniority == Seniority.GRADUATE
    assert years is None


def test_bare_intern_title(taxonomy: Taxonomy) -> None:
    seniority, _years = parse_seniority("Software Engineer Intern", "", taxonomy=taxonomy)
    assert seniority == Seniority.INTERN
