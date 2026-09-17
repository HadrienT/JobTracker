from jobtracker.core.enums import RoleFamily
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.normalize.title import classify_role, clean_title


def test_clean_title_removes_requisition_code() -> None:
    assert clean_title("Quant Developer REQ-104882") == "Quant Developer"


def test_clean_title_removes_gender_markers() -> None:
    assert clean_title("Développeur (H/F)") == "Développeur"
    assert clean_title("Ingénieur Logiciel (F/H)") == "Ingénieur Logiciel"


def test_clean_title_removes_year_mentions() -> None:
    assert clean_title("Graduate Software Engineer (2027 Start)") == "Graduate Software Engineer"
    assert clean_title("Analyst, Class of 2026") == "Analyst"


def test_clean_title_keeps_the_raw_title_when_nothing_is_left() -> None:
    assert clean_title("(H/F)") == "(H/F)"


def test_swe_at_a_prop_shop_is_not_other(taxonomy: Taxonomy) -> None:
    # blueprint/10-PROFILE-TARGET.md §2's discriminating case.
    result = classify_role(
        "Software Engineer", "Join our trading technology team.", taxonomy=taxonomy
    )
    assert result == RoleFamily.SWE_PLATFORM
    assert result != RoleFamily.OTHER


def test_sales_trader_is_quant_trading_not_other(taxonomy: Taxonomy) -> None:
    assert classify_role("US ETF Sales Trader", "", taxonomy=taxonomy) == RoleFamily.QUANT_TRADING


def test_mechanical_engineer_is_other(taxonomy: Taxonomy) -> None:
    assert classify_role("Mechanical Design Engineer", "", taxonomy=taxonomy) == RoleFamily.OTHER


def test_quantitative_developer_is_quant_dev(taxonomy: Taxonomy) -> None:
    assert classify_role("Quantitative Developer", "", taxonomy=taxonomy) == RoleFamily.QUANT_DEV


def test_data_engineer_is_data_eng_even_though_it_contains_engineer(taxonomy: Taxonomy) -> None:
    assert classify_role("Data Engineer", "", taxonomy=taxonomy) == RoleFamily.DATA_ENG


def test_research_scientist_is_quant_research_not_quant_dev(taxonomy: Taxonomy) -> None:
    # "Engineer"/"Developer" is the engineering track; "Scientist" is not,
    # even with an "AI" context word earlier in the same title.
    assert (
        classify_role("AI Research Scientist", "", taxonomy=taxonomy) == RoleFamily.QUANT_RESEARCH
    )


def test_campus_ai_research_engineer_is_quant_dev(taxonomy: Taxonomy) -> None:
    assert (
        classify_role("Campus AI Research Engineer", "", taxonomy=taxonomy) == RoleFamily.QUANT_DEV
    )
