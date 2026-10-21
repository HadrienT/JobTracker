"""Matching hand-written employer names, titles and places — WP21 §3."""

import pytest

from jobtracker.career.names import (
    alias_map,
    company_key,
    name_leftover,
    place_agreement,
    places,
    title_tokens,
)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Man Group", "ManGroup"),
        ("Société Générale", "Societe Generale"),
        ("Headlands Technologies", "HeadlandsTech"),
        ("Selby Jennings (Recruter)", "Selby Jennings"),
        ("Morgan Stanley", "MorganStanley"),
        ("Zimmer Partners LP", "Zimmer"),
    ],
)
def test_spellings_of_one_employer_share_a_key(left: str, right: str) -> None:
    assert company_key(left) == company_key(right)


def test_aliases_join_what_spelling_cannot() -> None:
    aliases = alias_map({"qrt": ["qube", "qubert"]})
    keys = {company_key(name, aliases) for name in ("QRT", "QubeRT", "Qube Research & Tech")}
    assert keys == {"qrt"}


def test_a_short_name_keeps_its_suffix_rather_than_vanish() -> None:
    assert company_key("Man Group") == "man"
    assert company_key("Group E") == "e"


def test_title_tokens_fold_synonyms_and_drop_places() -> None:
    assert title_tokens("Quant Dev NY") == title_tokens("Quantitative Developer, New York")
    assert title_tokens("SWE Cpp") == {"sw", "eng", "c++"}


def test_place_agreement_grades_cities_then_regions() -> None:
    assert place_agreement(places("USA (New York) NY"), places("Quant Dev NY")) == 3
    assert place_agreement(places("UK (London) -> SG"), places("Quant Dev London")) == 2
    assert place_agreement(places("HK / Singapore"), places("Analyst Asia")) == 1
    assert place_agreement(places("Singapore"), places("Quant Dev NY")) == -3
    assert place_agreement(places("CH (Zurich)"), places("Quant Dev")) is None


def test_name_leftover_is_the_title_hidden_in_a_company_name() -> None:
    assert name_leftover("Google Gemini", "Google") == "gemini"
    assert name_leftover("Aquatic Capital Management (Quant)", "Aquatic Capital") == "quant"
    assert name_leftover("Selby Jennings (Recruter)", "Selby Jennings") == ""
