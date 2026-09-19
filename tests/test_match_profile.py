"""Profile loader contract tests — blueprint/06-CONFIG.md §3."""

from pathlib import Path
from typing import Any

import pytest

from jobtracker.core.errors import ConfigError
from jobtracker.match.profile import Profile, build_profile, load_profile

REPO_ROOT = Path(__file__).resolve().parent.parent

_MINIMAL: dict[str, Any] = {
    "version": 1,
    "titles": {"strong": ["quant developer"], "possible": ["software engineer"], "excluded": []},
    "seniority": {"accept_if_years_max": 3, "reject": ["senior"]},
    "hard_rejects": {"phd_required": True, "min_years_above": 4, "stale_after_days": 60},
    "weights": {
        "title_strong": 35,
        "title_possible": 18,
        "sector_tier1": 12,
        "tech_cpp": 10,
        "tech_python": 6,
        "tech_niche": 8,
        "seniority_match": 20,
        "graduate_programme": 10,
        "visa_sponsors": 8,
        "visa_no": -25,
        "salary_disclosed": 3,
        "freshness_7d": 6,
        "stale_penalty": -10,
    },
    "tiers": {"strong": 70, "possible": 45, "stretch": 25},
    "freshness": {"window_days": 7, "stale_penalty_fraction": 0.5},
    "llm": {
        "min_description_chars": 200,
        "high_confidence_margin": 20,
        "min_confidence": 0.6,
        "max_description_chars": 6000,
    },
    "review": {
        "version": 1,
        "override_confidence": 0.8,
        "evidence_min_chars": 6,
        "max_locations": 8,
        "max_per_collect": 300,
        "max_output_tokens": 1200,
        "max_description_chars": 12000,
        "salary_bounds": {
            "year": [10000, 10000000],
            "month": [500, 500000],
            "day": [20, 20000],
            "hour": [5, 5000],
        },
        "currencies": ["USD", "EUR", "GBP", "CHF", "SGD", "HKD"],
        "currency_symbols": {"$": ["USD", "SGD", "HKD"], "£": ["GBP"], "€": ["EUR"]},
    },
}


def test_loads_the_real_profile_yaml() -> None:
    profile = load_profile(REPO_ROOT / "configs" / "profile.yaml")
    assert profile.version == 1
    assert "quant developer" in profile.titles.strong
    assert profile.tiers.strong == 70


def test_builds_a_minimal_profile() -> None:
    profile = build_profile(_MINIMAL)
    assert isinstance(profile, Profile)
    assert profile.weights["title_strong"] == 35
    assert profile.company_tiers == {}


def test_company_tiers_are_carried_through() -> None:
    profile = build_profile(_MINIMAL, company_tiers={"jane_street": 1, "some_vendor": 3})
    assert profile.company_tiers == {"jane_street": 1, "some_vendor": 3}


def test_missing_weight_key_is_rejected() -> None:
    weights = {k: v for k, v in _MINIMAL["weights"].items() if k != "visa_no"}
    data = {**_MINIMAL, "weights": weights}
    with pytest.raises(ConfigError, match="visa_no"):
        build_profile(data)


def test_missing_version_is_rejected() -> None:
    data = {k: v for k, v in _MINIMAL.items() if k != "version"}
    with pytest.raises(ConfigError):
        build_profile(data)


def test_an_alternative_profile_changes_behaviour_not_code() -> None:
    # blueprint/wp/WP05-match.md §7: no weight, threshold or title list may
    # live in code — swapping the profile data must be enough to change it.
    alternative = {
        **_MINIMAL,
        "tiers": {"strong": 1, "possible": 1, "stretch": 1},
    }
    profile = build_profile(alternative)
    assert profile.tiers.strong == 1
