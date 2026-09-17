from pathlib import Path

import pytest

from jobtracker.core.errors import ConfigError
from jobtracker.normalize.taxonomy import build_taxonomy, load_taxonomy

REPO_ROOT = Path(__file__).parent.parent
TAXONOMY_PATH = REPO_ROOT / "configs" / "taxonomy.yaml"


def test_loads_the_real_taxonomy_yaml() -> None:
    taxonomy = load_taxonomy(TAXONOMY_PATH)
    assert taxonomy.version == 1
    assert "cpp" in taxonomy.tech.aliases
    assert taxonomy.role_families.other_keywords


def test_rejects_missing_version() -> None:
    with pytest.raises(ConfigError):
        build_taxonomy({})


def test_rejects_non_mapping_role_families() -> None:
    with pytest.raises(ConfigError):
        build_taxonomy({"version": 1, "role_families": "nope"})
