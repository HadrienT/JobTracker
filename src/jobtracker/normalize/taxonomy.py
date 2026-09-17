"""`Taxonomy`, loaded from configs/taxonomy.yaml — pure, no I/O.

Mirrors the shape of `core.geo.GeoIndex`: a plain frozen structure built once
by `runtime` and passed into every stage, so a stage never opens a file
itself (contract D8, blueprint/01-ARCHITECTURE.md §2). Business keyword lists
live in the YAML (blueprint/09-CONVENTIONS.md §6); only the matching grammar
lives here.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jobtracker.core.config import load_yaml
from jobtracker.core.errors import ConfigError


def _require_list(data: Mapping[str, Any], key: str, *, where: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ConfigError(f"taxonomy config{where}: '{key}' must be a list")
    return tuple(str(v) for v in value)


@dataclass(frozen=True)
class RoleFamilyRules:
    other_keywords: tuple[str, ...]
    quant_trading_keywords: tuple[str, ...]
    quant_research_keywords: tuple[str, ...]
    data_eng_keywords: tuple[str, ...]
    risk_keywords: tuple[str, ...]
    quant_dev_strong_keywords: tuple[str, ...]
    quant_dev_context_keywords: tuple[str, ...]
    swe_infra_context_keywords: tuple[str, ...]
    engineering_head_words: tuple[str, ...]
    research_head_words: tuple[str, ...]


@dataclass(frozen=True)
class SeniorityRules:
    program_keywords: tuple[str, ...]
    title_keywords: Mapping[str, tuple[str, ...]]
    years_patterns: tuple[str, ...]


@dataclass(frozen=True)
class VisaRules:
    sponsors_phrases: tuple[str, ...]
    no_phrases: tuple[str, ...]
    restriction_phrases: tuple[str, ...]


@dataclass(frozen=True)
class TechRules:
    aliases: Mapping[str, tuple[str, ...]]
    ambiguous_single_token: Mapping[str, str]


@dataclass(frozen=True)
class LanguageRules:
    markers: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class Taxonomy:
    version: int
    role_families: RoleFamilyRules = field(repr=False)
    seniority: SeniorityRules = field(repr=False)
    visa: VisaRules = field(repr=False)
    tech: TechRules = field(repr=False)
    language: LanguageRules = field(repr=False)


def build_taxonomy(data: Mapping[str, Any], *, source: Path | str | None = None) -> Taxonomy:
    """Build a `Taxonomy` from already-loaded YAML data — pure, no I/O."""
    where = f" ({source})" if source is not None else ""
    try:
        version = int(data["version"])
    except KeyError as exc:
        raise ConfigError(f"taxonomy config{where}: missing 'version'") from exc

    rf = data.get("role_families")
    if not isinstance(rf, dict):
        raise ConfigError(f"taxonomy config{where}: 'role_families' must be a mapping")
    quant_dev = rf.get("quant_dev", {})
    swe_platform = rf.get("swe_platform", {})
    role_families = RoleFamilyRules(
        other_keywords=_require_list(rf.get("other", {}), "keywords", where=where),
        quant_trading_keywords=_require_list(rf.get("quant_trading", {}), "keywords", where=where),
        quant_research_keywords=_require_list(
            rf.get("quant_research", {}), "keywords", where=where
        ),
        data_eng_keywords=_require_list(rf.get("data_eng", {}), "keywords", where=where),
        risk_keywords=_require_list(rf.get("risk", {}), "keywords", where=where),
        quant_dev_strong_keywords=_require_list(quant_dev, "strong_keywords", where=where),
        quant_dev_context_keywords=_require_list(quant_dev, "context_keywords", where=where),
        swe_infra_context_keywords=_require_list(
            swe_platform, "infra_context_keywords", where=where
        ),
        engineering_head_words=_require_list(data, "engineering_head_words", where=where),
        research_head_words=_require_list(data, "research_head_words", where=where),
    )

    sen = data.get("seniority")
    if not isinstance(sen, dict):
        raise ConfigError(f"taxonomy config{where}: 'seniority' must be a mapping")
    title_keywords_raw = sen.get("title_keywords", {})
    if not isinstance(title_keywords_raw, dict):
        raise ConfigError(f"taxonomy config{where}: 'seniority.title_keywords' must be a mapping")
    seniority = SeniorityRules(
        program_keywords=_require_list(sen, "program_keywords", where=where),
        title_keywords={k: tuple(str(x) for x in v) for k, v in title_keywords_raw.items()},
        years_patterns=_require_list(sen, "years_patterns", where=where),
    )

    visa_raw = data.get("visa")
    if not isinstance(visa_raw, dict):
        raise ConfigError(f"taxonomy config{where}: 'visa' must be a mapping")
    visa = VisaRules(
        sponsors_phrases=_require_list(visa_raw, "sponsors_phrases", where=where),
        no_phrases=_require_list(visa_raw, "no_phrases", where=where),
        restriction_phrases=_require_list(visa_raw, "restriction_phrases", where=where),
    )

    tech_raw = data.get("tech")
    if not isinstance(tech_raw, dict):
        raise ConfigError(f"taxonomy config{where}: 'tech' must be a mapping")
    aliases_raw = tech_raw.get("aliases", {})
    if not isinstance(aliases_raw, dict):
        raise ConfigError(f"taxonomy config{where}: 'tech.aliases' must be a mapping")
    ambiguous_raw = tech_raw.get("ambiguous_single_token", {})
    if not isinstance(ambiguous_raw, dict):
        raise ConfigError(
            f"taxonomy config{where}: 'tech.ambiguous_single_token' must be a mapping"
        )
    tech = TechRules(
        aliases={k: tuple(str(x) for x in v) for k, v in aliases_raw.items()},
        ambiguous_single_token={k: str(v) for k, v in ambiguous_raw.items()},
    )

    lang_raw = data.get("language")
    if not isinstance(lang_raw, dict):
        raise ConfigError(f"taxonomy config{where}: 'language' must be a mapping")
    markers_raw = lang_raw.get("markers", {})
    if not isinstance(markers_raw, dict):
        raise ConfigError(f"taxonomy config{where}: 'language.markers' must be a mapping")
    language = LanguageRules(markers={k: tuple(str(x) for x in v) for k, v in markers_raw.items()})

    return Taxonomy(
        version=version,
        role_families=role_families,
        seniority=seniority,
        visa=visa,
        tech=tech,
        language=language,
    )


def load_taxonomy(path: Path) -> Taxonomy:
    """Load and build the `Taxonomy` from `configs/taxonomy.yaml` (or an equivalent)."""
    return build_taxonomy(load_yaml(path), source=path)
