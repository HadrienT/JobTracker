"""The target profile, loaded from configs/profile.yaml — blueprint/06-CONFIG.md §3.

Mirrors normalize.taxonomy's pattern: parsed once from already-loaded YAML
data, then passed to `evaluate`/`hard_reject` as an argument — zero I/O
inside `match` itself (contract D4). `company_tiers` (a company_slug ->
registry priority mapping) travels the same way: it comes from
configs/companies.yaml, but `match` never reads that file or imports
`collect` — whoever assembles a `Profile` hands it the mapping already built.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from jobtracker.core.config import load_yaml
from jobtracker.core.errors import ConfigError

_REQUIRED_WEIGHTS = (
    "title_strong",
    "title_possible",
    "sector_tier1",
    "tech_cpp",
    "tech_python",
    "tech_niche",
    "seniority_match",
    "graduate_programme",
    "visa_sponsors",
    "visa_no",
    "salary_disclosed",
    "freshness_7d",
    "stale_penalty",
)


@dataclass(frozen=True)
class TitleRules:
    strong: tuple[str, ...]
    possible: tuple[str, ...]
    excluded: tuple[str, ...]


@dataclass(frozen=True)
class SeniorityRules:
    accept_if_years_max: int
    reject_keywords: tuple[str, ...]


@dataclass(frozen=True)
class HardRejectRules:
    phd_required: bool
    min_years_above: int
    stale_after_days: int


@dataclass(frozen=True)
class Tiers:
    strong: int
    possible: int
    stretch: int


@dataclass(frozen=True)
class FreshnessRules:
    window_days: int
    stale_penalty_fraction: float


@dataclass(frozen=True)
class LlmRules:
    min_description_chars: int
    high_confidence_margin: int
    min_confidence: float
    max_description_chars: int


@dataclass(frozen=True)
class ReviewRules:
    version: int
    override_confidence: float
    evidence_min_chars: int
    max_locations: int
    max_per_collect: int
    max_output_tokens: int
    max_description_chars: int
    salary_bounds: Mapping[str, tuple[Decimal, Decimal]]
    currencies: frozenset[str]
    currency_symbols: Mapping[str, frozenset[str]]


@dataclass(frozen=True)
class Profile:
    version: int
    titles: TitleRules
    seniority: SeniorityRules
    hard_rejects: HardRejectRules
    weights: Mapping[str, int]
    tiers: Tiers
    freshness: FreshnessRules
    llm: LlmRules
    review: ReviewRules
    company_tiers: Mapping[str, int]


def _str_tuple(data: Mapping[str, Any], key: str, *, where: str) -> tuple[str, ...]:
    raw = data.get(key, [])
    if not isinstance(raw, list):
        raise ConfigError(f"profile{where}: '{key}' must be a list")
    return tuple(str(v) for v in raw)


def build_profile(
    data: Mapping[str, Any],
    *,
    company_tiers: Mapping[str, int] | None = None,
    source: Path | str | None = None,
) -> Profile:
    """Build a `Profile` from already-loaded YAML data — pure, no I/O."""
    where = f" ({source})" if source is not None else ""
    try:
        version = int(data["version"])
    except KeyError as exc:
        raise ConfigError(f"profile{where}: missing field {exc}") from exc

    raw_titles = data.get("titles", {})
    if not isinstance(raw_titles, dict):
        raise ConfigError(f"profile{where}: 'titles' must be a mapping")
    titles = TitleRules(
        strong=_str_tuple(raw_titles, "strong", where=where),
        possible=_str_tuple(raw_titles, "possible", where=where),
        excluded=_str_tuple(raw_titles, "excluded", where=where),
    )

    raw_seniority = data.get("seniority", {})
    if not isinstance(raw_seniority, dict):
        raise ConfigError(f"profile{where}: 'seniority' must be a mapping")
    try:
        seniority = SeniorityRules(
            accept_if_years_max=int(raw_seniority["accept_if_years_max"]),
            reject_keywords=_str_tuple(raw_seniority, "reject", where=where),
        )
    except KeyError as exc:
        raise ConfigError(f"profile{where}: 'seniority' is missing field {exc}") from exc

    raw_hard_rejects = data.get("hard_rejects", {})
    if not isinstance(raw_hard_rejects, dict):
        raise ConfigError(f"profile{where}: 'hard_rejects' must be a mapping")
    try:
        hard_rejects = HardRejectRules(
            phd_required=bool(raw_hard_rejects["phd_required"]),
            min_years_above=int(raw_hard_rejects["min_years_above"]),
            stale_after_days=int(raw_hard_rejects["stale_after_days"]),
        )
    except KeyError as exc:
        raise ConfigError(f"profile{where}: 'hard_rejects' is missing field {exc}") from exc

    raw_weights = data.get("weights", {})
    if not isinstance(raw_weights, dict):
        raise ConfigError(f"profile{where}: 'weights' must be a mapping")
    missing = [key for key in _REQUIRED_WEIGHTS if key not in raw_weights]
    if missing:
        raise ConfigError(f"profile{where}: 'weights' is missing {missing}")
    try:
        weights = {key: int(value) for key, value in raw_weights.items()}
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"profile{where}: 'weights' has a non-integer value ({exc})") from exc

    raw_tiers = data.get("tiers", {})
    if not isinstance(raw_tiers, dict):
        raise ConfigError(f"profile{where}: 'tiers' must be a mapping")
    try:
        tiers = Tiers(
            strong=int(raw_tiers["strong"]),
            possible=int(raw_tiers["possible"]),
            stretch=int(raw_tiers["stretch"]),
        )
    except KeyError as exc:
        raise ConfigError(f"profile{where}: 'tiers' is missing field {exc}") from exc

    raw_freshness = data.get("freshness", {})
    if not isinstance(raw_freshness, dict):
        raise ConfigError(f"profile{where}: 'freshness' must be a mapping")
    try:
        freshness = FreshnessRules(
            window_days=int(raw_freshness["window_days"]),
            stale_penalty_fraction=float(raw_freshness["stale_penalty_fraction"]),
        )
    except KeyError as exc:
        raise ConfigError(f"profile{where}: 'freshness' is missing field {exc}") from exc

    raw_llm = data.get("llm", {})
    if not isinstance(raw_llm, dict):
        raise ConfigError(f"profile{where}: 'llm' must be a mapping")
    try:
        llm = LlmRules(
            min_description_chars=int(raw_llm["min_description_chars"]),
            high_confidence_margin=int(raw_llm["high_confidence_margin"]),
            min_confidence=float(raw_llm["min_confidence"]),
            max_description_chars=int(raw_llm["max_description_chars"]),
        )
    except KeyError as exc:
        raise ConfigError(f"profile{where}: 'llm' is missing field {exc}") from exc

    raw_review = data.get("review", {})
    if not isinstance(raw_review, dict):
        raise ConfigError(f"profile{where}: 'review' must be a mapping")
    try:
        raw_bounds = raw_review["salary_bounds"]
        salary_bounds = {
            str(period): (Decimal(str(low)), Decimal(str(high)))
            for period, (low, high) in raw_bounds.items()
        }
        review = ReviewRules(
            version=int(raw_review["version"]),
            override_confidence=float(raw_review["override_confidence"]),
            evidence_min_chars=int(raw_review["evidence_min_chars"]),
            max_locations=int(raw_review["max_locations"]),
            max_per_collect=int(raw_review["max_per_collect"]),
            max_output_tokens=int(raw_review["max_output_tokens"]),
            max_description_chars=int(raw_review["max_description_chars"]),
            salary_bounds=salary_bounds,
            currencies=frozenset(str(code).upper() for code in raw_review["currencies"]),
            currency_symbols={
                str(symbol): frozenset(str(c).upper() for c in codes)
                for symbol, codes in raw_review["currency_symbols"].items()
            },
        )
    except KeyError as exc:
        raise ConfigError(f"profile{where}: 'review' is missing field {exc}") from exc
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ConfigError(f"profile{where}: 'review' has a malformed value: {exc}") from exc

    return Profile(
        version=version,
        titles=titles,
        seniority=seniority,
        hard_rejects=hard_rejects,
        weights=weights,
        tiers=tiers,
        freshness=freshness,
        llm=llm,
        review=review,
        company_tiers=dict(company_tiers) if company_tiers is not None else {},
    )


def load_profile(path: Path, *, company_tiers: Mapping[str, int] | None = None) -> Profile:
    """Load and build the `Profile` from `configs/profile.yaml` (or an equivalent)."""
    return build_profile(load_yaml(path), company_tiers=company_tiers, source=path)
