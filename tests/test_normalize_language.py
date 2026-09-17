from jobtracker.normalize.language import detect_language, parse_languages_required
from jobtracker.normalize.taxonomy import Taxonomy


def test_detects_english_by_default(taxonomy: Taxonomy) -> None:
    assert detect_language("We are looking for a Software Engineer.", taxonomy=taxonomy) == "en"


def test_detects_french(taxonomy: Taxonomy) -> None:
    text = "Nous recherchons un développeur pour rejoindre notre équipe."
    assert detect_language(text, taxonomy=taxonomy) == "fr"


def test_detects_german(taxonomy: Taxonomy) -> None:
    text = "Wir suchen einen Ingenieur mit Erfahrung mit modernen Systemen."
    assert detect_language(text, taxonomy=taxonomy) == "de"


def test_english_word_containing_a_french_marker_does_not_trigger_french(
    taxonomy: Taxonomy,
) -> None:
    # "candidate" must not satisfy the French marker "candidat".
    text = "The ideal candidate has strong analytical skills and clear communication."
    assert detect_language(text, taxonomy=taxonomy) == "en"


def test_bilingual_requirement_is_detected(taxonomy: Taxonomy) -> None:
    required = parse_languages_required(
        "You must be bilingual in French and English to succeed in this role.",
        taxonomy=taxonomy,
    )
    assert {"fr", "en"} <= required
