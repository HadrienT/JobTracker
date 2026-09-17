from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.normalize.techstack import parse_tech


def test_common_aliases(taxonomy: Taxonomy) -> None:
    tech = parse_tech("We use C++, Python, and kdb+ extensively.", taxonomy=taxonomy)
    assert tech == frozenset({"cpp", "python", "kdb"})


def test_go_as_a_verb_is_not_the_language(taxonomy: Taxonomy) -> None:
    tech = parse_tech("Go get the report, then go live with it.", taxonomy=taxonomy)
    assert "go" not in tech


def test_go_in_a_tech_list_is_the_language(taxonomy: Taxonomy) -> None:
    tech = parse_tech("Strong skills in Go, Python, and Rust required.", taxonomy=taxonomy)
    assert tech == frozenset({"go", "python", "rust"})


def test_bare_r_in_a_word_is_not_the_language(taxonomy: Taxonomy) -> None:
    tech = parse_tech("Our HR team partners with R&D on hiring.", taxonomy=taxonomy)
    assert "r" not in tech


def test_r_in_a_tech_list_is_the_language(taxonomy: Taxonomy) -> None:
    tech = parse_tech("Experience with R, Python, and SQL.", taxonomy=taxonomy)
    assert tech == frozenset({"r", "python", "sql"})


def test_no_tech_mentioned_is_an_empty_set(taxonomy: Taxonomy) -> None:
    assert (
        parse_tech("A great opportunity for a motivated individual.", taxonomy=taxonomy)
        == frozenset()
    )
