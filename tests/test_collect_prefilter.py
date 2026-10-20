"""`collect.prefilter` — which titles are worth a description request."""

import pytest

from jobtracker.collect.prefilter import looks_relevant

pytestmark = pytest.mark.contract


@pytest.mark.parametrize(
    "title",
    [
        "Quantitative Developer",
        "C++ Software Engineer",
        "Corporate Bank Strat",
        "Credit Strats - Associate",
        "Stage - Analyste Quantitatif H/F",
        "Développeur Python Front Office",
        "Ingénieur Pricing Dérivés Actions",
        "V.I.E. Cross Asset Retail Sales (m/f/d)",
        "VIE - Structurer - London",
        "2027 Off Cycle Internship Programme",
        "Graduate Programme - Markets",
        "Model Validation Analyst",
        "Werkstudent IT",
        "XVA Analyst",
    ],
)
def test_a_title_that_could_matter_is_worth_a_request(title: str) -> None:
    assert looks_relevant(title)


@pytest.mark.parametrize(
    "title",
    [
        "Branch Teller",
        "Chargé d’Affaires Professionnels - H/F",
        "Conseiller Clientèle Essentiel",
        "Middle Officer assurance vie - H/F",  # "vie" the word, not the contract
        "Senior Relationship Manager, Priority",
        "Legal Counsel in Corporate Finance",
        "Privatkundenberater*in",
        "Executive Assistant (f/m/d)",
    ],
)
def test_a_title_no_profile_wants_is_not(title: str) -> None:
    assert not looks_relevant(title)


def test_case_does_not_matter() -> None:
    assert looks_relevant("QUANT DEV")
    assert looks_relevant("quant dev")
