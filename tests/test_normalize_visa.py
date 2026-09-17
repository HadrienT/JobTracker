from jobtracker.core.enums import VisaStatus
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.normalize.visa import parse_visa


def test_double_negation_is_no_not_sponsors(taxonomy: Taxonomy) -> None:
    # blueprint/wp/WP03-normalize.md §3: "sponsorship" appears, but this is NO.
    status, evidence = parse_visa(
        "We are unable to provide sponsorship at this time.", taxonomy=taxonomy
    )
    assert status == VisaStatus.NO
    assert evidence is not None


def test_disguised_restriction_is_no(taxonomy: Taxonomy) -> None:
    status, _ = parse_visa("This role is Remote (US only).", taxonomy=taxonomy)
    assert status == VisaStatus.NO


def test_explicit_sponsorship_offered(taxonomy: Taxonomy) -> None:
    status, evidence = parse_visa(
        "Visa sponsorship available for the right candidate.", taxonomy=taxonomy
    )
    assert status == VisaStatus.SPONSORS
    assert evidence is not None


def test_silence_is_unknown_never_no(taxonomy: Taxonomy) -> None:
    status, evidence = parse_visa("A great opportunity to join our team.", taxonomy=taxonomy)
    assert status == VisaStatus.UNKNOWN
    assert evidence is None


def test_no_is_checked_before_sponsors(taxonomy: Taxonomy) -> None:
    status, _ = parse_visa(
        "We will not sponsor candidates, though we do sponsor local conferences.",
        taxonomy=taxonomy,
    )
    assert status == VisaStatus.NO
