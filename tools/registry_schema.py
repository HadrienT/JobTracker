"""Structural validation of configs/companies.yaml.

This is deliberately not just `jobtracker.core.models.Board`: that DTO is the
*resolved* runtime shape (`company_slug`, `company_name`), one rename step away
from the raw YAML keys (`slug`, `name`) documented in blueprint/06-CONFIG.md §2.
`RegistryEntry` validates the on-disk file itself — the artifact WP00 owns —
while still reusing `core.enums.Source` as the single source of truth for which
ATS families are valid, now that WP01 has landed.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from jobtracker.core.enums import Source

SLUG_RE = re.compile(r"^[a-z][a-z0-9_]*$")
# Aggregators (WP13) are never a per-company registry source: a company's
# entry names the ATS that hosts its board, not the aggregator that might
# also republish it.
_AGGREGATOR_SOURCES = {Source.EFC, Source.WTTJ, Source.LINKEDIN, Source.INDEED}
VALID_SOURCES = frozenset(s.value for s in Source if s not in _AGGREGATOR_SOURCES)
VALID_SECTORS = frozenset(
    {"hedge_fund", "prop_trading", "bank", "asset_manager", "vendor", "crypto"}
)


class RegistryEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slug: str
    name: str
    source: str
    token: str
    extra: dict[str, str] = {}
    sector: str
    hq_country: str
    priority: int
    enabled: bool
