from datetime import UTC, datetime

from jobtracker.core.hashing import content_hash, fingerprint


def test_content_hash_changes_on_one_character() -> None:
    a = content_hash("Quant Developer", "Build pricing systems.", "London")
    b = content_hash("Quant Developer", "Build pricing systems!", "London")
    assert a != b


def test_content_hash_is_stable() -> None:
    a = content_hash("Quant Developer", "Build pricing systems.", "London")
    b = content_hash("Quant Developer", "Build pricing systems.", "London")
    assert a == b


def test_fingerprint_ignores_gender_and_start_year_noise() -> None:
    posted_at = datetime(2026, 1, 10, tzinfo=UTC)
    a = fingerprint("jane_street", "Quantitative Developer", "US", posted_at)
    b = fingerprint("jane_street", "Quantitative Developer (f/h) — 2026 start", "US", posted_at)
    assert a == b


def test_fingerprint_differs_for_distinct_postings_same_company() -> None:
    posted_at = datetime(2026, 1, 10, tzinfo=UTC)
    a = fingerprint("jane_street", "Quantitative Developer", "US", posted_at)
    b = fingerprint("jane_street", "Quantitative Researcher", "US", posted_at)
    assert a != b


def test_fingerprint_unknown_country_uses_placeholder() -> None:
    a = fingerprint("optiver", "Quant Developer", None, None)
    b = fingerprint("optiver", "Quant Developer", "??", None)
    assert a == b


def test_fingerprint_is_deterministic_without_posted_at() -> None:
    a = fingerprint("optiver", "Quant Developer", "NL", None)
    b = fingerprint("optiver", "Quant Developer", "NL", None)
    assert a == b


def test_fingerprint_same_bucket_within_14_days() -> None:
    a = fingerprint("optiver", "Quant Developer", "NL", datetime(2026, 1, 1, tzinfo=UTC))
    b = fingerprint("optiver", "Quant Developer", "NL", datetime(2026, 1, 10, tzinfo=UTC))
    assert a == b


def test_fingerprint_different_bucket_beyond_14_days() -> None:
    a = fingerprint("optiver", "Quant Developer", "NL", datetime(2026, 1, 1, tzinfo=UTC))
    b = fingerprint("optiver", "Quant Developer", "NL", datetime(2026, 3, 1, tzinfo=UTC))
    assert a != b
