"""The aggregators' single entry point — the only module `runtime` ever loads.

`runtime.aggregator_loader` imports this by *string*, inside a `try`, so that
`rm -rf collect/aggregators/` leaves everything else importable and green
(blueprint/wp/WP13-aggregators.md §5-6). A collector whose credentials are missing
is simply not registered — "unavailable", not an exception — so a missing key
never crashes a run (forbidden n°14: nothing depends on this lot).
"""

import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from jobtracker.collect.aggregators.adzuna import AdzunaCollector
from jobtracker.collect.aggregators.common import resolver
from jobtracker.collect.aggregators.efinancialcareers import EfcCollector
from jobtracker.collect.aggregators.impersonation import CurlCffiClient
from jobtracker.collect.aggregators.indeed import IndeedCollector
from jobtracker.collect.base import AggregatorSetup, Collector
from jobtracker.collect.http import HttpClient
from jobtracker.core.config import load_yaml
from jobtracker.core.enums import Source
from jobtracker.core.errors import ConfigError
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board

_logger = get_logger(__name__)

_PLACEHOLDERS = frozenset({"", "replace-me"})
_SLUG = re.compile(r"[^a-z0-9]+")


def _has(value: str | None) -> bool:
    return value is not None and value.strip() not in _PLACEHOLDERS


def _pseudo_boards(source: Source, block: Mapping[str, Any]) -> list[Board]:
    shared = {k: str(v) for k, v in block.items() if k != "queries"}
    boards = []
    for i, query in enumerate(block.get("queries", [])):
        if not isinstance(query, dict) or "what" not in query:
            raise ConfigError(f"aggregators.yaml: {source.value} query {i} needs a 'what'")
        extra = {**shared, **{k: str(v) for k, v in query.items() if k != "what"}}
        country = extra.get("country") or extra.get("domain", "").split(".")[0] or ""
        key = _SLUG.sub("-", f"{query['what']}-{extra.get('where', '')}-{country}".lower()).strip(
            "-"
        )
        boards.append(
            Board(
                company_slug=f"{source.value}:{key}",
                company_name=f"{source.value} search: {query['what']}",
                source=source,
                token=str(query["what"]),
                extra=extra,
                sector="aggregator",
                hq_country=country.upper()[:2],
                priority=1,
                enabled=True,
            )
        )
    return boards


def build(
    *,
    registry_boards: Iterable[Board],
    config_path: Path,
    adzuna_app_id: str | None,
    adzuna_app_key: str | None,
    linkedin_cookie: str | None,
) -> AggregatorSetup:
    config = load_yaml(config_path)
    collectors: dict[Source, Collector] = {}
    factories: dict[Source, Callable[[], HttpClient]] = {}
    boards: list[Board] = []

    if _has(adzuna_app_id) and _has(adzuna_app_key):
        collectors[Source.ADZUNA] = AdzunaCollector(
            app_id=str(adzuna_app_id), app_key=str(adzuna_app_key)
        )
        boards += _pseudo_boards(Source.ADZUNA, config.get("adzuna", {}))
    else:
        _logger.info("aggregator_unavailable", source="adzuna", reason="no API credentials")

    collectors[Source.EFC] = EfcCollector()
    boards += _pseudo_boards(Source.EFC, config.get("efinancialcareers", {}))

    collectors[Source.INDEED] = IndeedCollector()
    factories[Source.INDEED] = CurlCffiClient
    boards += _pseudo_boards(Source.INDEED, config.get("indeed", {}))

    if _has(linkedin_cookie):
        _logger.warning(
            "aggregator_not_implemented",
            source="linkedin",
            reason="robots.txt disallows /jobs-guest/; not collected",
        )
    return AggregatorSetup(
        collectors=collectors,
        boards=boards,
        client_factories=factories,
        resolve_employer=resolver(registry_boards),
    )
