"""Registry contract tests — blueprint/wp/WP04-collect-core.md §4.

An invalid entry must fail startup naming the slug, never degrade to a
silent `enabled: false` (the registry is source code, ADR-009).
"""

from pathlib import Path

import pytest

from jobtracker.collect.registry import boards_for_source, build_registry, load_registry
from jobtracker.core.enums import Source
from jobtracker.core.errors import ConfigError
from jobtracker.core.models import Board

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.contract


def _entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "slug": "acme",
        "name": "Acme",
        "source": "greenhouse",
        "token": "acme",
        "sector": "prop_trading",
        "hq_country": "US",
        "priority": 1,
        "enabled": True,
    }
    base.update(overrides)
    return base


def test_loads_the_real_companies_yaml() -> None:
    boards = load_registry(REPO_ROOT / "configs" / "companies.yaml")
    assert len(boards) > 100
    assert all(isinstance(b, Board) for b in boards)


def test_builds_a_board_from_a_valid_entry() -> None:
    boards = build_registry([_entry()])
    assert boards == [
        Board(
            company_slug="acme",
            company_name="Acme",
            source=Source.GREENHOUSE,
            token="acme",
            sector="prop_trading",
            hq_country="US",
            priority=1,
            enabled=True,
        )
    ]


def test_missing_field_names_the_slug() -> None:
    entry = _entry()
    del entry["priority"]
    with pytest.raises(ConfigError, match="acme"):
        build_registry([entry])


def test_invalid_source_names_the_slug() -> None:
    with pytest.raises(ConfigError, match="acme"):
        build_registry([_entry(source="not_a_real_ats")])


def test_duplicate_slug_is_rejected() -> None:
    with pytest.raises(ConfigError, match="acme"):
        build_registry([_entry(), _entry()])


def test_non_list_top_level_is_rejected() -> None:
    with pytest.raises(ConfigError):
        build_registry({"not": "a list"})  # type: ignore[arg-type]


def test_boards_for_source_orders_by_priority_then_slug() -> None:
    boards = build_registry(
        [
            _entry(slug="b", priority=2),
            _entry(slug="a", priority=2),
            _entry(slug="z", priority=1),
        ]
    )
    ordered = boards_for_source(boards, Source.GREENHOUSE)
    assert [b.company_slug for b in ordered] == ["z", "a", "b"]


def test_boards_for_source_excludes_disabled_by_default() -> None:
    boards = build_registry([_entry(slug="on", enabled=True), _entry(slug="off", enabled=False)])
    assert [b.company_slug for b in boards_for_source(boards, Source.GREENHOUSE)] == ["on"]


def test_boards_for_source_excludes_other_sources() -> None:
    boards = build_registry(
        [_entry(slug="gh", source="greenhouse"), _entry(slug="lv", source="lever")]
    )
    assert [b.company_slug for b in boards_for_source(boards, Source.LEVER)] == ["lv"]
