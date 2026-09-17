import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from jobtracker.core.config import Settings, load_settings, load_yaml
from jobtracker.core.errors import ConfigError

_ALL_ENV = {
    "JT_DB_PATH": "./jobtracker.db",
    "JT_LOG_LEVEL": "INFO",
    "JT_LOG_FORMAT": "json",
    "JT_API_HOST": "127.0.0.1",
    "JT_API_PORT": "8100",
    "JT_WEB_PORT": "5190",
    "JT_PUBLIC_API_BASE": "http://127.0.0.1:8100",
    "JT_LLM_ENABLED": "false",
    "JT_LLM_BASE_URL": "http://127.0.0.1:8000/v1",
    "JT_LLM_MODEL": "Qwen3-Coder-30B-A3B-Instruct",
    "JT_LLM_TIMEOUT_S": "60",
    "JT_USER_AGENT": "JobTracker/0.1 (+contact)",
    "JT_HTTP_TIMEOUT_S": "20",
    "JT_AGGREGATORS_ENABLED": "false",
}


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith("JT_"):
            monkeypatch.delenv(key, raising=False)
    yield


def test_settings_loads_every_field_typed(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _ALL_ENV.items():
        monkeypatch.setenv(key, value)
    settings = load_settings(env_file=None)
    assert isinstance(settings, Settings)
    assert settings.db_path == Path("./jobtracker.db")
    assert settings.api_port == 8100
    assert settings.llm_enabled is False
    assert settings.aggregators_enabled is False
    assert settings.adzuna_app_id is None


def test_settings_optional_secrets_default_to_none(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in _ALL_ENV.items():
        monkeypatch.setenv(key, value)
    settings = load_settings(env_file=None)
    assert settings.adzuna_app_id is None
    assert settings.adzuna_app_key is None
    assert settings.linkedin_cookie is None


def test_missing_required_variable_fails_startup_naming_the_field(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    incomplete = dict(_ALL_ENV)
    del incomplete["JT_DB_PATH"]
    for key, value in incomplete.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ConfigError, match="JT_DB_PATH"):
        load_settings(env_file=None)


def test_load_yaml_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_yaml(tmp_path / "missing.yaml")


def test_load_yaml_invalid_syntax_names_the_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("cities: [this is: not: valid", encoding="utf-8")
    with pytest.raises(ConfigError, match=str(bad)):
        load_yaml(bad)


def test_load_yaml_rejects_non_mapping_top_level(tmp_path: Path) -> None:
    not_a_mapping = tmp_path / "list.yaml"
    not_a_mapping.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_yaml(not_a_mapping)


def test_load_yaml_valid_mapping(tmp_path: Path) -> None:
    path = tmp_path / "ok.yaml"
    path.write_text("a: 1\nb: two\n", encoding="utf-8")
    assert load_yaml(path) == {"a": 1, "b": "two"}
