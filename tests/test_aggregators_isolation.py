"""`rm -rf src/jobtracker/collect/aggregators/` leaves the suite green — WP13 §5, §6.

The last row of the blueprint's test table, "celle qui prouve son isolement":
this one really deletes the package (from a copy) and runs the rest.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from jobtracker.core.config import Settings
from jobtracker.runtime import aggregator_loader
from jobtracker.runtime.aggregator_loader import load_aggregators

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_the_first_lock_disabled_means_no_import_and_no_setup(
    settings_factory: Callable[..., Settings],
) -> None:
    assert (
        load_aggregators(
            settings_factory(aggregators_enabled=False), [], configs_dir=REPO_ROOT / "configs"
        )
        is None
    )


def test_an_absent_package_is_no_aggregators_not_an_error(
    monkeypatch: pytest.MonkeyPatch, settings_factory: Callable[..., Settings]
) -> None:
    def gone(name: str) -> None:
        raise ModuleNotFoundError(f"No module named {name!r}", name=name)

    monkeypatch.setattr(aggregator_loader.importlib, "import_module", gone)
    result = load_aggregators(
        settings_factory(aggregators_enabled=True), [], configs_dir=REPO_ROOT / "configs"
    )
    assert result is None


def test_a_missing_third_party_dependency_is_not_swallowed(
    monkeypatch: pytest.MonkeyPatch, settings_factory: Callable[..., Settings]
) -> None:
    def broken(name: str) -> None:
        raise ModuleNotFoundError("No module named 'somelib'", name="somelib")

    monkeypatch.setattr(aggregator_loader.importlib, "import_module", broken)
    with pytest.raises(ModuleNotFoundError):
        load_aggregators(
            settings_factory(aggregators_enabled=True), [], configs_dir=REPO_ROOT / "configs"
        )


def test_the_project_runs_and_its_tests_pass_with_the_package_deleted(tmp_path: Path) -> None:
    ignore = shutil.ignore_patterns("__pycache__")
    for name in ("src", "tests", "configs", "blueprint", "tools", "deploy", "scripts"):
        shutil.copytree(REPO_ROOT / name, tmp_path / name, ignore=ignore)
    shutil.copytree(REPO_ROOT / "migrations", tmp_path / "migrations")
    for name in ("pyproject.toml", "docker-compose.prod.yml", ".env.example"):
        shutil.copy(REPO_ROOT / name, tmp_path / name)
    (tmp_path / "web").mkdir()
    for name in (
        "Dockerfile.prod",
        "nginx.conf.template",
        "security-headers.conf",
        "40-jt-config.sh",
    ):
        shutil.copy(REPO_ROOT / "web" / name, tmp_path / "web" / name)  # not node_modules
    shutil.rmtree(tmp_path / "src" / "jobtracker" / "collect" / "aggregators")
    # This very test would recurse. The tests of the deleted package must simply
    # not be collected (tests/conftest.py) — everything else must pass untouched.
    (tmp_path / "tests" / "test_aggregators_isolation.py").unlink()

    env = {**os.environ, "PYTHONPATH": str(tmp_path / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2500:] + result.stderr[-1500:]
    assert "passed" in result.stdout
