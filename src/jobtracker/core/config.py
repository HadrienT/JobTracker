"""`Settings` and the YAML loader — the only place that reads `os.environ` or
opens a configuration file (blueprint/06-CONFIG.md, rule C2).

No field below carries a silent fallback: a variable absent from the
environment and without a default fails startup loudly, naming the field —
see rule C3. Business defaults live in `.env.example`, not in this module.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from jobtracker.core.errors import ConfigError


class Settings(BaseSettings):
    """Every environment-level setting, prefixed `JT_` — blueprint/06-CONFIG.md §1."""

    model_config = SettingsConfigDict(env_prefix="JT_", extra="ignore")

    db_path: Path
    log_level: str
    log_format: str
    api_host: str
    api_port: int
    web_port: int
    public_api_base: str
    llm_enabled: bool
    llm_base_url: str
    llm_model: str
    llm_timeout_s: int
    user_agent: str
    http_timeout_s: int
    aggregators_enabled: bool
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    linkedin_cookie: str | None = None


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    """Build `Settings` from the environment (and `env_file` if it exists).

    Raises `ConfigError` naming every missing or invalid `JT_*` variable,
    instead of letting a silent default hide a startup mistake.
    """
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        raise ConfigError(_format_settings_error(exc)) from exc


def _format_settings_error(exc: ValidationError) -> str:
    lines = [f"invalid settings ({exc.error_count()} error(s)):"]
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"])
        env_var = f"JT_{field.upper()}"
        lines.append(f"  - {env_var}: {error['msg']}")
    return "\n".join(lines)


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping, raising `ConfigError` naming the file and the cause."""
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise ConfigError(f"invalid YAML in {path}{location}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a YAML mapping at the top level")
    return data
