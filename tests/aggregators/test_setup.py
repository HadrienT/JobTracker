"""`aggregators.setup`, the curl_cffi adapter and the shared cadence — WP13 §3.4, §5."""

import sys
import types
from pathlib import Path

import httpx
import pytest

from factories_store import make_board
from jobtracker.collect.aggregators.impersonation import CurlCffiClient
from jobtracker.collect.aggregators.setup import build
from jobtracker.collect.base import AggregatorSetup
from jobtracker.collect.http import PolicedHttpSession, SourceHttpConfig, load_sources_config
from jobtracker.core.enums import Source
from jobtracker.core.errors import SourceUnavailable

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[2]


def _build(**creds: str | None) -> AggregatorSetup:
    kwargs: dict[str, str | None] = {
        "adzuna_app_id": None,
        "adzuna_app_key": None,
        "linkedin_cookie": None,
    }
    kwargs.update(creds)
    return build(
        registry_boards=[make_board()],
        config_path=REPO_ROOT / "configs" / "aggregators.yaml",
        **kwargs,
    )


def test_adzuna_is_unavailable_without_credentials_and_the_run_carries_on() -> None:
    setup = _build()
    assert Source.ADZUNA not in setup.collectors
    assert not [b for b in setup.boards if b.source == Source.ADZUNA]


@pytest.mark.parametrize("placeholder", ["replace-me", "", "   "])
def test_the_env_example_placeholder_is_not_a_credential(placeholder: str) -> None:
    setup = _build(adzuna_app_id=placeholder, adzuna_app_key=placeholder)
    assert Source.ADZUNA not in setup.collectors


def test_adzuna_registers_with_credentials() -> None:
    setup = _build(adzuna_app_id="id", adzuna_app_key="key")
    assert Source.ADZUNA in setup.collectors
    boards = [b for b in setup.boards if b.source == Source.ADZUNA]
    assert boards and all(b.extra["country"] for b in boards)


def test_every_query_becomes_a_uniquely_slugged_pseudo_board() -> None:
    boards = _build().boards
    slugs = [b.company_slug for b in boards]
    assert len(slugs) == len(set(slugs))
    assert all(b.sector == "aggregator" and b.enabled for b in boards)


def test_linkedin_and_wttj_are_not_collected() -> None:
    setup = _build(linkedin_cookie="li_at=whatever")
    assert Source.LINKEDIN not in setup.collectors
    assert Source.WTTJ not in setup.collectors


def test_only_indeed_needs_tls_impersonation() -> None:
    assert set(_build().client_factories) == {Source.INDEED}


def test_every_aggregator_source_ships_disabled() -> None:
    config = load_sources_config(REPO_ROOT / "configs" / "sources.yaml")
    for source in (Source.ADZUNA, Source.EFC, Source.WTTJ, Source.LINKEDIN, Source.INDEED):
        assert config.is_enabled(source) is False, source


def test_fragile_sources_have_the_wide_jitter_and_the_long_interval() -> None:
    config = load_sources_config(REPO_ROOT / "configs" / "sources.yaml")
    for source in (Source.EFC, Source.LINKEDIN, Source.INDEED):
        assert config.for_source(source).jitter_s == (20, 90)
        assert config.interval_min[str(source)] >= 720


def test_jitter_is_respected_across_twenty_requests() -> None:
    config = load_sources_config(REPO_ROOT / "configs" / "sources.yaml").for_source(Source.EFC)
    now = 0.0
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    session = PolicedHttpSession(
        client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="x"))),
        config=SourceHttpConfig(
            timeout_s=config.timeout_s,
            max_requests_per_run=100,
            jitter_s=config.jitter_s,
        ),
        user_agent="t",
        sleep=sleep,
        rand=lambda low, _high: low,  # the *shortest* wait the config allows
        clock=lambda: now,
    )
    for _ in range(20):
        session.get_text("https://example.test/x")
    assert len(sleeps) == 19  # nothing to wait for before the first request
    assert min(sleeps) >= 20


def _fake_curl(monkeypatch: pytest.MonkeyPatch, request: object) -> None:
    class _Timeout(Exception):
        pass

    class _RequestException(Exception):
        pass

    exceptions = types.SimpleNamespace(Timeout=_Timeout, RequestException=_RequestException)
    module = types.ModuleType("curl_cffi.requests")
    module.request = request
    module.exceptions = exceptions
    package = types.ModuleType("curl_cffi")
    package.requests = module
    monkeypatch.setitem(sys.modules, "curl_cffi", package)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", module)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests.exceptions", exceptions)  # type: ignore[arg-type]


def test_the_adapter_drops_the_honest_user_agent_and_the_stale_encoding_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def request(method: str, url: str, **kwargs: object) -> object:
        seen.update(kwargs)
        return types.SimpleNamespace(
            status_code=200,
            headers={"Content-Encoding": "gzip", "Content-Type": "text/html"},
            content=b"<html>ok</html>",
        )

    _fake_curl(monkeypatch, request)
    response = CurlCffiClient().request(
        "GET", "https://x.test", headers={"User-Agent": "JobTracker/0.1", "Accept": "text/html"}
    )
    assert seen["headers"] == {"Accept": "text/html"}  # curl sends the impersonated browser's UA
    assert seen["impersonate"] == "chrome"
    assert (response.status_code, response.text) == (200, "<html>ok</html>")
    assert "content-encoding" not in response.headers  # curl already decoded the body


def test_a_curl_timeout_becomes_the_httpx_timeout_the_session_understands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def request(method: str, url: str, **kwargs: object) -> object:
        raise sys.modules["curl_cffi.requests.exceptions"].Timeout("slow")

    _fake_curl(monkeypatch, request)
    with pytest.raises(httpx.TimeoutException):
        CurlCffiClient().request("GET", "https://x.test")


def test_a_missing_curl_cffi_is_a_per_board_failure_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules, "curl_cffi", None
    )  # makes `import curl_cffi` raise ImportError
    with pytest.raises(SourceUnavailable):
        CurlCffiClient().request("GET", "https://x.test")
