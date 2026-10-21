"""Matching hand-written employer names, titles and places — WP21 §3."""

import pytest

from jobtracker.career.countries import application_countries, countries_in
from jobtracker.career.names import (
    alias_map,
    company_key,
    name_leftover,
    place_agreement,
    places,
    title_tokens,
)
from jobtracker.core.geo import GeoIndex


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


# --- countries: the sheet's colour code, read off the text -----------------------------------


@pytest.mark.parametrize(
    ("location", "countries"),
    [
        ("CH (Zurich)", ("CH",)),
        ("UK (London) -> SG", ("GB", "SG")),
        ("USA (Jersey City)NJ", ("US",)),
        ("USA (Chicago) IL", ("US",)),  # Illinois, not Israel
        ("CA (Montreal)", ("CA",)),  # Canada, not California
        ("Singapore/HK", ("SG", "HK")),
        ("HK / Singapore", ("HK", "SG")),
        ("Amsterdam / Chicago", ("NL", "US")),
        ("Sinpagore", ("SG",)),
        ("EU (Paris/Zurich)", ("FR", "CH")),
        ("New York, US · Greenwich, US", ("US",)),
        ("London, GB (hybrid)", ("GB",)),
        ("Global", ()),
        (None, ()),
    ],
)
def test_countries_in_the_sheet_and_feed_formats(
    location: str | None, countries: tuple[str, ...]
) -> None:
    assert countries_in(location) == countries


def test_a_job_title_only_counts_unmistakable_codes() -> None:
    assert application_countries(None, "Quant Research SG") == ("SG",)
    assert application_countries(None, "IT Support Analyst") == ()
    assert application_countries("CH (Zug)", "Quant Dev SG") == ("CH",)  # the location wins


def test_the_referential_resolves_only_a_city_with_one_country(geo_index: GeoIndex) -> None:
    unique = next(
        city
        for city, entries in geo_index.by_city.items()
        if len({e.country for e in entries}) == 1 and city.lower() not in {"london"}
    )
    country = geo_index.by_city[unique][0].country
    assert countries_in(unique.lower(), geo=geo_index) == (country,)
    # London is the sheet's own word for the UK; any other homonym stays unresolved.
    homonyms = [
        c
        for c, e in geo_index.by_city.items()
        if len({x.country for x in e}) > 1 and not countries_in(c.lower())
    ]
    assert homonyms, "the referential has homonyms (Cambridge, London…)"
    assert countries_in(homonyms[0].lower(), geo=geo_index) == ()
