"""`configs/companies.yaml` → the collection plan — blueprint/wp/WP04-collect-core.md §4.

The registry is source code (ADR-009): an invalid entry fails startup naming
the offending slug, the same way a syntax error fails a build. It never
degrades to a silent `enabled: false` — that would make a typo indistinguishable
from a company that stopped hiring.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jobtracker.core.config import load_yaml_list
from jobtracker.core.enums import Source
from jobtracker.core.errors import ConfigError
from jobtracker.core.models import Board


def build_registry(data: list[Any], *, source: Path | str | None = None) -> list[Board]:
    """Build the list of `Board` from already-loaded YAML data — pure, no I/O."""
    where = f" ({source})" if source is not None else ""
    if not isinstance(data, list):
        raise ConfigError(f"companies registry{where}: expected a YAML list at the top level")

    boards: list[Board] = []
    seen_slugs: set[str] = set()
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ConfigError(f"companies registry{where}: entry {i} must be a mapping")
        slug = entry.get("slug")
        label = f"{slug!r}" if slug else f"entry {i}"
        try:
            board = Board(
                company_slug=str(entry["slug"]),
                company_name=str(entry["name"]),
                source=Source(entry["source"]),
                token=str(entry["token"]),
                extra={str(k): str(v) for k, v in entry.get("extra", {}).items()},
                sector=str(entry["sector"]),
                hq_country=str(entry["hq_country"]),
                priority=int(entry["priority"]),
                enabled=bool(entry["enabled"]),
            )
        except KeyError as exc:
            raise ConfigError(f"companies registry{where}: {label} is missing field {exc}") from exc
        except ValueError as exc:
            raise ConfigError(f"companies registry{where}: {label} is invalid: {exc}") from exc
        if board.company_slug in seen_slugs:
            raise ConfigError(f"companies registry{where}: duplicate slug {board.company_slug!r}")
        seen_slugs.add(board.company_slug)
        boards.append(board)
    return boards


def load_registry(path: Path) -> list[Board]:
    """Load and build the registry from `configs/companies.yaml` (or an equivalent)."""
    return build_registry(load_yaml_list(path), source=path)


def boards_for_source(
    boards: Iterable[Board], source: Source, *, only_enabled: bool = True
) -> list[Board]:
    """The collection plan for one ATS family: matching boards, priority first (1 before 3)."""
    matching = [b for b in boards if b.source == source and (b.enabled or not only_enabled)]
    return sorted(matching, key=lambda b: (b.priority, b.company_slug))
