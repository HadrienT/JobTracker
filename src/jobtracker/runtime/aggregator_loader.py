"""The only place `runtime` reaches for `collect/aggregators/` — and only by string.

blueprint/wp/WP13-aggregators.md §6: `rm -rf src/jobtracker/collect/aggregators/`
must leave the project importable and its tests green. A static `import` here
would break that the moment the directory is gone; `importlib` inside a `try`
turns "the directory is missing" into "no aggregators", which is exactly the
state `JT_AGGREGATORS_ENABLED=false` already is. `import-linter` (contract D10)
forbids every other static import of the package.
"""

import importlib
from collections.abc import Iterable
from pathlib import Path
from typing import cast

from jobtracker.collect.base import AggregatorSetup
from jobtracker.core.config import Settings
from jobtracker.core.logging import get_logger
from jobtracker.core.models import Board

_logger = get_logger(__name__)

_SETUP_MODULE = "jobtracker.collect.aggregators.setup"


def load_aggregators(
    settings: Settings, registry_boards: Iterable[Board], *, configs_dir: Path
) -> AggregatorSetup | None:
    """`None` when the first lock (`JT_AGGREGATORS_ENABLED`) is off or the package is absent.

    The second lock — `enabled: true` per source in `sources.yaml` — is applied by
    the loop, exactly as for any ATS.
    """
    if not settings.aggregators_enabled:
        return None
    try:
        module = importlib.import_module(_SETUP_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name is not None and exc.name.startswith("jobtracker.collect.aggregators"):
            _logger.info("aggregators_package_absent")
            return None
        raise
    setup = module.build(
        registry_boards=list(registry_boards),
        config_path=configs_dir / "aggregators.yaml",
        adzuna_app_id=settings.adzuna_app_id,
        adzuna_app_key=settings.adzuna_app_key,
        linkedin_cookie=settings.linkedin_cookie,
    )
    return cast(AggregatorSetup, setup)
