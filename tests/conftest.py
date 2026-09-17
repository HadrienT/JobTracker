"""Shared pytest fixtures."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def geo_config_path() -> Path:
    return REPO_ROOT / "configs" / "geo.yaml"
