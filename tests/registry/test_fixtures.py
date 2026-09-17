"""Every WP04 ATS family must have a reference payload — blueprint/08-TESTING.md §3.

These fixtures are the prerequisite for WP04's collector contract tests: without
a real captured payload, a "nominal response" test would work against invented
JSON that drifts from what the ATS actually serves.
"""

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "payloads"
WP04_FAMILIES = ("greenhouse", "lever", "ashby")


@pytest.mark.parametrize("family", WP04_FAMILIES)
def test_wp04_family_has_a_reference_payload(family: str) -> None:
    directory = FIXTURES_DIR / family
    assert directory.is_dir(), f"no fixtures captured for {family}"
    payloads = list(directory.glob("*.json"))
    assert payloads, f"{family} has a directory but no captured payload"
    for path in payloads:
        json.loads(path.read_text(encoding="utf-8"))  # must be valid JSON
