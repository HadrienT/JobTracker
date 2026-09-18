"""Contract tests for the shared HTTP policy — blueprint/11-SOURCES.md §6.

No real network: every response comes from an `httpx.MockTransport`, and time
never actually passes — `sleep`/`rand`/`clock` are all injected fakes, per
blueprint/wp/WP04-collect-core.md §6's "vérifié par une horloge factice".
"""

import random
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from jobtracker.collect.http import (
    BUDGET_EXHAUSTED,
    NOT_MODIFIED,
    PolicedHttpSession,
    SourceHttpConfig,
    build_sources_config,
    load_sources_config,
)
from jobtracker.core.errors import (
    BoardNotFound,
    ConfigError,
    SourceBlocked,
    SourceSchemaChanged,
    SourceUnavailable,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.contract


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _session(
    handler: httpx.MockTransport,
    *,
    config: SourceHttpConfig | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rand: Callable[[float, float], float] = random.uniform,
    clock: Callable[[], float] = time.monotonic,
) -> PolicedHttpSession:
    return PolicedHttpSession(
        client=httpx.Client(transport=handler),
        config=config or SourceHttpConfig(),
        user_agent="JobTracker-Test/1.0",
        sleep=sleep,
        rand=rand,
        clock=clock,
    )


def test_nominal_get_json_returns_the_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == "JobTracker-Test/1.0"
        return httpx.Response(200, json={"jobs": [1, 2, 3]})

    session = _session(httpx.MockTransport(handler))
    assert session.get_json("https://example.com/jobs") == {"jobs": [1, 2, 3]}
    assert session.requests_made == 1
    assert session.truncated is False


def test_404_raises_board_not_found_not_source_unavailable() -> None:
    session = _session(httpx.MockTransport(lambda request: httpx.Response(404)))
    with pytest.raises(BoardNotFound):
        session.get_json("https://example.com/jobs")


@pytest.mark.parametrize("status", [403, 429])
def test_403_429_raise_source_blocked(status: int) -> None:
    session = _session(httpx.MockTransport(lambda request: httpx.Response(status)))
    with pytest.raises(SourceBlocked):
        session.get_json("https://example.com/jobs")


def test_403_429_never_retry_immediately() -> None:
    # blueprint/00-PRIMER.md interdit n°8: the session itself must not sleep
    # waiting out a backoff — that decision belongs to the runtime circuit
    # breaker (WP08), across separate runs, not to a blocking call here.
    calls: list[float] = []
    session = _session(
        httpx.MockTransport(lambda request: httpx.Response(429)),
        sleep=calls.append,
    )
    with pytest.raises(SourceBlocked):
        session.get_json("https://example.com/jobs")
    assert calls == []


@pytest.mark.parametrize("status", [500, 502, 503])
def test_5xx_raises_source_unavailable(status: int) -> None:
    session = _session(httpx.MockTransport(lambda request: httpx.Response(status)))
    with pytest.raises(SourceUnavailable):
        session.get_json("https://example.com/jobs")


def test_timeout_raises_source_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom", request=request)

    session = _session(httpx.MockTransport(handler))
    with pytest.raises(SourceUnavailable):
        session.get_json("https://example.com/jobs")


def test_unrecognizable_payload_raises_source_schema_changed() -> None:
    session = _session(
        httpx.MockTransport(lambda request: httpx.Response(200, content=b"not json"))
    )
    with pytest.raises(SourceSchemaChanged):
        session.get_json("https://example.com/jobs")


def test_budget_exhausted_is_not_an_exception() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json={"jobs": []})

    session = _session(
        httpx.MockTransport(handler), config=SourceHttpConfig(max_requests_per_run=1)
    )
    assert session.get_json("https://example.com/a") == {"jobs": []}
    assert session.get_json("https://example.com/b") is BUDGET_EXHAUSTED
    assert len(calls) == 1  # the second call never reached the transport
    assert session.truncated is True
    assert session.requests_made == 1


def test_get_text_on_budget_exhausted_returns_empty_string() -> None:
    session = _session(
        httpx.MockTransport(lambda request: httpx.Response(200, text="body")),
        config=SourceHttpConfig(max_requests_per_run=0),
    )
    assert session.get_text("https://example.com/a") == ""


def test_jitter_paces_two_consecutive_requests() -> None:
    clock = _FakeClock()
    sleeps: list[float] = []
    session = _session(
        httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        config=SourceHttpConfig(jitter_s=(5.0, 5.0)),
        clock=clock,
        sleep=lambda s: (sleeps.append(s), clock.advance(s)),
        rand=lambda lo, hi: 5.0,
    )
    session.get_json("https://example.com/a")
    assert sleeps == []  # no prior request to pace against
    clock.advance(1.0)  # only 1s elapsed since the first request
    session.get_json("https://example.com/b")
    assert sleeps == [4.0]  # topped up to the configured 5s minimum


def test_jitter_skipped_when_enough_time_already_elapsed() -> None:
    clock = _FakeClock()
    sleeps: list[float] = []
    session = _session(
        httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        config=SourceHttpConfig(jitter_s=(2.0, 2.0)),
        clock=clock,
        sleep=sleeps.append,
        rand=lambda lo, hi: 2.0,
    )
    session.get_json("https://example.com/a")
    clock.advance(10.0)
    session.get_json("https://example.com/b")
    assert sleeps == []


def test_etag_round_trip_sends_conditional_request_and_handles_304() -> None:
    responses = [
        httpx.Response(200, json={"jobs": [1]}, headers={"ETag": '"abc123"'}),
        httpx.Response(304),
    ]
    seen_headers = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers.get("If-None-Match"))
        return responses.pop(0)

    session = _session(httpx.MockTransport(handler))
    first = session.get_json("https://example.com/jobs")
    second = session.get_json("https://example.com/jobs")

    assert first == {"jobs": [1]}
    assert second is NOT_MODIFIED
    assert seen_headers == [None, '"abc123"']


def test_sources_config_loads_the_real_file() -> None:
    config = load_sources_config(REPO_ROOT / "configs" / "sources.yaml")
    assert config.defaults.jitter_s == (2.0, 7.0)
    assert config.defaults.max_requests_per_run == 200
    assert config.is_enabled("greenhouse") is True
    assert config.is_enabled("workday") is False
    assert config.for_source("workday").max_requests_per_run == 400
    assert config.empty_runs_before_alert == 3


def test_sources_config_rejects_a_non_mapping_defaults_block() -> None:
    with pytest.raises(ConfigError):
        build_sources_config({"defaults": ["not", "a", "mapping"]})


def test_sources_config_source_override_falls_back_to_defaults() -> None:
    config = build_sources_config(
        {"defaults": {"timeout_s": 20}, "sources": {"greenhouse": {"enabled": True}}}
    )
    assert config.for_source("greenhouse").timeout_s == 20.0
    assert config.for_source("unconfigured_source") is config.defaults
