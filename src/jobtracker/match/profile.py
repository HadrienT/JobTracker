"""The target profile, loaded from configs/profile.yaml — blueprint/06-CONFIG.md §3.

Mirrors normalize.taxonomy's pattern: parsed once from already-loaded YAML
data, then passed to `evaluate`/`hard_reject` as an argument — zero I/O
inside `match` itself (contract D4). `company_tiers` (a company_slug ->
registry priority mapping) travels the same way: it comes from
configs/companies.yaml, but `match` never reads that file or imports
`collect` — whoever assembles a `Profile` hands it the mapping already built.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from jobtracker.core.config import load_yaml
from jobtracker.core.enums import Track
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
class ScopeRules:
    """Which postings a profile scores at all — blueprint/wp/WP20-tracks.md §2.

    `countries` empty means everywhere (the quant feed); a track names its own. A posting
    of an `exclude_sectors` employer is rejected as off target: the quant feed is not where
    a robotics start-up's C++ role belongs, even when its title reads like one.
    """

    countries: frozenset[str] = frozenset()
    exclude_sectors: frozenset[str] = frozenset()


@dataclass(frozen=True)
class TopicRules:
    """What a track is about: a title keyword or a tech tag puts a posting in scope."""

    titles: tuple[str, ...]
    tech: frozenset[str]


# The quant feed's niche tags, used when profile.yaml does not name its own.
DEFAULT_NICHE_TECH = frozenset({"kdb", "ocaml", "rust", "cuda", "fpga"})


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
    niche_tech: frozenset[str] = DEFAULT_NICHE_TECH
    scope: ScopeRules = ScopeRules()
    # None for the quant feed, whose subject is its role families; set for a track.
    topic: TopicRules | None = None
    # company_slug -> registry sector, handed over like `company_tiers` (no I/O in match).
    company_sectors: Mapping[str, str] = field(default_factory=dict)


def _str_tuple(data: Mapping[str, Any], key: str, *, where: str) -> tuple[str, ...]:
    raw = data.get(key, [])
    if not isinstance(raw, list):
        raise ConfigError(f"profile{where}: '{key}' must be a list")
    return tuple(str(v) for v in raw)


def _build_scope(data: Mapping[str, Any], *, where: str) -> ScopeRules:
    raw = data.get("scope", {})
    if not isinstance(raw, dict):
        raise ConfigError(f"profile{where}: 'scope' must be a mapping")
    return ScopeRules(
        countries=frozenset(c.upper() for c in _str_tuple(raw, "countries", where=where)),
        exclude_sectors=frozenset(_str_tuple(raw, "exclude_sectors", where=where)),
    )


def _build_topic(data: Mapping[str, Any], *, where: str) -> TopicRules | None:
    raw = data.get("topic")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(f"profile{where}: 'topic' must be a mapping")
    topic = TopicRules(
        titles=tuple(t.lower() for t in _str_tuple(raw, "titles", where=where)),
        tech=frozenset(_str_tuple(raw, "tech", where=where)),
    )
    if not topic.titles and not topic.tech:
        raise ConfigError(f"profile{where}: 'topic' names neither titles nor tech")
    return topic


def build_profile(
    data: Mapping[str, Any],
    *,
    company_tiers: Mapping[str, int] | None = None,
    company_sectors: Mapping[str, str] | None = None,
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
        niche_tech=(
            frozenset(_str_tuple(data, "niche_tech", where=where))
            if "niche_tech" in data
            else DEFAULT_NICHE_TECH
        ),
        scope=_build_scope(data, where=where),
        topic=_build_topic(data, where=where),
        company_sectors=dict(company_sectors) if company_sectors is not None else {},
    )


def load_profile(
    path: Path,
    *,
    company_tiers: Mapping[str, int] | None = None,
    company_sectors: Mapping[str, str] | None = None,
) -> Profile:
    """Load and build the `Profile` from `configs/profile.yaml` (or an equivalent)."""
    return build_profile(
        load_yaml(path), company_tiers=company_tiers, company_sectors=company_sectors, source=path
    )


def _overlay(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    """`over` on top of `base`: mappings merge key by key, anything else is replaced."""
    merged = dict(base)
    for key, value in over.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _overlay(current, value)
        else:
            merged[key] = value
    return merged


def build_tracks(
    base: Mapping[str, Any],
    tracks: Mapping[str, Any],
    *,
    company_tiers: Mapping[str, int] | None = None,
    company_sectors: Mapping[str, str] | None = None,
    source: Path | str | None = None,
) -> dict[Track, Profile]:
    """One `Profile` per track: the track's overlay on top of the quant profile's data.

    A track inherits everything it does not restate — the LLM lanes, the staleness rule, the
    seniority keywords — so what tracks.yaml shows is exactly how the track differs.
    """
    where = f" ({source})" if source is not None else ""
    raw = tracks.get("tracks", {})
    if not isinstance(raw, dict):
        raise ConfigError(f"tracks{where}: 'tracks' must be a mapping")
    known = {t.value for t in Track}
    profiles: dict[Track, Profile] = {}
    for name, over in raw.items():
        if name not in known:
            raise ConfigError(f"tracks{where}: unknown track {name!r} (core.enums.Track)")
        if not isinstance(over, dict) or "version" not in over:
            raise ConfigError(f"tracks{where}: track {name!r} needs its own 'version'")
        profiles[Track(name)] = build_profile(
            _overlay(base, over),
            company_tiers=company_tiers,
            company_sectors=company_sectors,
            source=f"{source}:{name}" if source is not None else name,
        )
    return profiles


def load_tracks(
    profile_path: Path,
    tracks_path: Path,
    *,
    company_tiers: Mapping[str, int] | None = None,
    company_sectors: Mapping[str, str] | None = None,
) -> dict[Track, Profile]:
    """`configs/tracks.yaml`, each track built on `configs/profile.yaml`. No file, no track."""
    if not tracks_path.exists():
        return {}
    return build_tracks(
        load_yaml(profile_path),
        load_yaml(tracks_path),
        company_tiers=company_tiers,
        company_sectors=company_sectors,
        source=tracks_path,
    )
