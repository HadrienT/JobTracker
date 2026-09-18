"""The one HTTP policy every source obeys — blueprint/11-SOURCES.md §6.

One request at a time, jittered, budgeted, honestly identified, backing off
on a block rather than hammering it. A collector that builds its own client
is a bug (blueprint/03-INTERFACES.md §3.1) — `import-linter` D8 only lets
this module and `match.llm` touch `httpx`, and review catches the rest.

Two conditions never raise, by design (blueprint/wp/WP04-collect-core.md §2,
§5): a request budget cut short, and a `304 Not Modified` reply. Both are
communicated to a collector through the sentinels below rather than an
exception, because neither is a failure.
"""

from __future__ import annotations

import json as jsonlib
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from jobtracker.core.config import load_yaml
from jobtracker.core.enums import Source
from jobtracker.core.errors import (
    BoardNotFound,
    ConfigError,
    SourceBlocked,
    SourceSchemaChanged,
    SourceUnavailable,
)


class HttpSession(Protocol):
    def get_json(self, url: str, *, params: Mapping[str, str] | None = None) -> Any: ...
    def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str: ...
    def post_json(self, url: str, *, json: Mapping[str, Any]) -> Any: ...


class _NotModified:
    """The `get_json`/`post_json` sentinel for a `304`: nothing changed."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "NOT_MODIFIED"


class _BudgetExhausted:
    """The `get_json`/`post_json` sentinel for a spent request budget."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "BUDGET_EXHAUSTED"


NOT_MODIFIED = _NotModified()
BUDGET_EXHAUSTED = _BudgetExhausted()


@dataclass(frozen=True)
class SourceHttpConfig:
    """The cadence one source is fetched at — configs/sources.yaml, per source."""

    timeout_s: float = 20.0
    max_requests_per_run: int = 200
    jitter_s: tuple[float, float] = (2.0, 7.0)
    backoff_base_s: float = 30.0
    backoff_max_s: float = 3600.0


@dataclass(frozen=True)
class SourcesConfig:
    defaults: SourceHttpConfig
    dedup_window_days: int
    enabled: Mapping[str, bool]
    interval_min: Mapping[str, int]
    overrides: Mapping[str, SourceHttpConfig]
    empty_runs_before_alert: int

    def for_source(self, source: Source | str) -> SourceHttpConfig:
        return self.overrides.get(str(source), self.defaults)

    def is_enabled(self, source: Source | str) -> bool:
        """Sources absent from `sources:` (not yet configured) default to on."""
        return self.enabled.get(str(source), True)


def build_sources_config(
    data: Mapping[str, Any], *, source: Path | str | None = None
) -> SourcesConfig:
    """Build a `SourcesConfig` from already-loaded YAML data — pure, no I/O."""
    where = f" ({source})" if source is not None else ""
    raw_defaults = data.get("defaults", {})
    if not isinstance(raw_defaults, dict):
        raise ConfigError(f"sources config{where}: 'defaults' must be a mapping")
    defaults = _build_http_config(raw_defaults, where=f"{where} defaults", base=SourceHttpConfig())
    dedup_window_days = raw_defaults.get("dedup_window_days", 14)
    if not isinstance(dedup_window_days, int):
        raise ConfigError(f"sources config{where}: 'defaults.dedup_window_days' must be an int")

    raw_sources = data.get("sources", {})
    if not isinstance(raw_sources, dict):
        raise ConfigError(f"sources config{where}: 'sources' must be a mapping")
    enabled: dict[str, bool] = {}
    interval_min: dict[str, int] = {}
    overrides: dict[str, SourceHttpConfig] = {}
    for name, entry in raw_sources.items():
        if not isinstance(entry, dict):
            raise ConfigError(f"sources config{where}: sources.{name} must be a mapping")
        enabled[str(name)] = bool(entry.get("enabled", True))
        interval = entry.get("interval_min")
        if interval is not None:
            interval_min[str(name)] = int(interval)
        overrides[str(name)] = _build_http_config(
            entry, where=f"{where} sources.{name}", base=defaults
        )

    raw_watchdog = data.get("watchdog", {})
    if not isinstance(raw_watchdog, dict):
        raise ConfigError(f"sources config{where}: 'watchdog' must be a mapping")
    empty_runs_before_alert = raw_watchdog.get("empty_runs_before_alert", 3)
    if not isinstance(empty_runs_before_alert, int):
        raise ConfigError(
            f"sources config{where}: 'watchdog.empty_runs_before_alert' must be an int"
        )

    return SourcesConfig(
        defaults=defaults,
        dedup_window_days=dedup_window_days,
        enabled=enabled,
        interval_min=interval_min,
        overrides=overrides,
        empty_runs_before_alert=empty_runs_before_alert,
    )


def _build_http_config(
    entry: Mapping[str, Any], *, where: str, base: SourceHttpConfig
) -> SourceHttpConfig:
    jitter = entry.get("jitter_s")
    try:
        return SourceHttpConfig(
            timeout_s=float(entry.get("timeout_s", base.timeout_s)),
            max_requests_per_run=int(entry.get("max_requests_per_run", base.max_requests_per_run)),
            jitter_s=(float(jitter[0]), float(jitter[1])) if jitter is not None else base.jitter_s,
            backoff_base_s=float(entry.get("backoff_base_s", base.backoff_base_s)),
            backoff_max_s=float(entry.get("backoff_max_s", base.backoff_max_s)),
        )
    except (TypeError, ValueError, IndexError) as exc:
        raise ConfigError(f"sources config{where}: invalid value ({exc})") from exc


def load_sources_config(path: Path) -> SourcesConfig:
    """Load and build the `SourcesConfig` from `configs/sources.yaml` (or an equivalent)."""
    return build_sources_config(load_yaml(path), source=path)


@dataclass
class PolicedHttpSession:
    """The only concrete `HttpSession` — every collector shares this policy.

    One instance is meant to be reused across every board of a single source
    within a run, so the jitter and the request budget apply across the whole
    run, not per board (blueprint/11-SOURCES.md §6).
    """

    client: httpx.Client
    config: SourceHttpConfig
    user_agent: str
    sleep: Callable[[float], None] = time.sleep
    rand: Callable[[float, float], float] = random.uniform
    clock: Callable[[], float] = time.monotonic
    requests_made: int = field(default=0, init=False)
    truncated: bool = field(default=False, init=False)
    _last_request_at: float | None = field(default=None, init=False, repr=False)
    _etags: dict[str, str] = field(default_factory=dict, init=False, repr=False)

    def get_json(self, url: str, *, params: Mapping[str, str] | None = None) -> Any:
        response = self._perform("GET", url, params=params)
        if not isinstance(response, httpx.Response):
            return response
        try:
            return response.json()
        except jsonlib.JSONDecodeError as exc:
            raise SourceSchemaChanged(f"200 but body is not valid JSON: {url}") from exc

    def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str:
        response = self._perform("GET", url, params=params)
        if not isinstance(response, httpx.Response):
            return ""
        return response.text

    def post_json(self, url: str, *, json: Mapping[str, Any]) -> Any:
        response = self._perform("POST", url, json=json)
        if not isinstance(response, httpx.Response):
            return response
        try:
            return response.json()
        except jsonlib.JSONDecodeError as exc:
            raise SourceSchemaChanged(f"200 but body is not valid JSON: {url}") from exc

    def _perform(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> httpx.Response | _NotModified | _BudgetExhausted:
        if self.requests_made >= self.config.max_requests_per_run:
            self.truncated = True
            return BUDGET_EXHAUSTED

        self._enforce_jitter()

        headers = {"User-Agent": self.user_agent}
        etag = self._etags.get(url)
        if etag is not None and method == "GET":
            headers["If-None-Match"] = etag

        try:
            response = self.client.request(
                method,
                url,
                params=params,
                json=json,
                headers=headers,
                timeout=self.config.timeout_s,
            )
        except httpx.TimeoutException as exc:
            raise SourceUnavailable(f"timeout calling {url}") from exc
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"network error calling {url}: {exc}") from exc

        self.requests_made += 1
        self._last_request_at = self.clock()

        if response.status_code == 304:
            return NOT_MODIFIED
        if response.status_code == 404:
            raise BoardNotFound(f"404 for {url}")
        if response.status_code in (403, 429):
            raise SourceBlocked(f"{response.status_code} for {url}")
        if response.status_code >= 500:
            raise SourceUnavailable(f"{response.status_code} for {url}")
        if response.status_code != 200:
            raise SourceUnavailable(f"unexpected status {response.status_code} for {url}")

        new_etag = response.headers.get("ETag")
        if new_etag:
            self._etags[url] = new_etag
        return response

    def _enforce_jitter(self) -> None:
        if self._last_request_at is None:
            return
        wait = self.rand(*self.config.jitter_s)
        elapsed = self.clock() - self._last_request_at
        remaining = wait - elapsed
        if remaining > 0:
            self.sleep(remaining)
