"""`match.llm` — blueprint/wp/WP12-match-llm.md §4-6.

No real network anywhere here: every response comes from an
`httpx.MockTransport`, mirroring `test_collect_http.py`'s own convention.
"""

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from factories_store import make_posting, make_verdict
from jobtracker.core.config import Settings
from jobtracker.core.enums import RoleFamily, Seniority, Tier, VisaStatus
from jobtracker.core.errors import LlmUnavailable
from jobtracker.match.llm import (
    LlmVerdict,
    apply_llm_verdict,
    classify_llm,
    resolve_residual,
)
from jobtracker.match.profile import Profile, build_profile

pytestmark = pytest.mark.contract

_BASE_URL = "http://127.0.0.1:8000/v1"
_MODEL = "Qwen3-Coder-30B-A3B-Instruct"
_LONG_DESCRIPTION = "We are hiring for this role. " * 20

_PROFILE_DATA = {
    "version": 1,
    "titles": {"strong": [], "possible": [], "excluded": []},
    "seniority": {"accept_if_years_max": 3, "reject": []},
    "hard_rejects": {"phd_required": True, "min_years_above": 4, "stale_after_days": 60},
    "weights": {
        "title_strong": 35,
        "title_possible": 18,
        "sector_tier1": 12,
        "tech_cpp": 10,
        "tech_python": 6,
        "tech_niche": 8,
        "seniority_match": 20,
        "graduate_programme": 10,
        "visa_sponsors": 8,
        "visa_no": -25,
        "salary_disclosed": 3,
        "freshness_7d": 6,
        "stale_penalty": -10,
    },
    "tiers": {"strong": 70, "possible": 45, "stretch": 25},
    "freshness": {"window_days": 7, "stale_penalty_fraction": 0.5},
    "llm": {
        "min_description_chars": 200,
        "high_confidence_margin": 20,
        "min_confidence": 0.6,
        "max_description_chars": 6000,
    },
}


def _profile(**company_tiers: int) -> Profile:
    return build_profile(_PROFILE_DATA, company_tiers=company_tiers)


_LLM_ON = {"llm_enabled": True, "llm_base_url": _BASE_URL, "llm_model": _MODEL}


def _chat_response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_classify_llm_returns_a_verdict_on_a_conforming_reply() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == f"{_BASE_URL}/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == _MODEL
        assert body["response_format"]["type"] == "json_schema"
        return _chat_response(
            {
                "role_family": "quant_dev",
                "seniority": "junior",
                "min_years": 1,
                "visa_sponsorship": "sponsors",
                "phd_required": False,
                "confidence": 0.9,
            }
        )

    posting = make_posting()
    verdict = classify_llm(
        posting,
        description=_LONG_DESCRIPTION,
        timeout_s=5,
        base_url=_BASE_URL,
        model=_MODEL,
        max_description_chars=6000,
        client=_client(handler),
    )
    assert verdict == LlmVerdict(
        role_family=RoleFamily.QUANT_DEV,
        seniority=Seniority.JUNIOR,
        min_years=1,
        visa_sponsorship=VisaStatus.SPONSORS,
        phd_required=False,
        confidence=0.9,
    )


def test_classify_llm_never_produces_a_score() -> None:
    assert "score" not in LlmVerdict.model_fields


def test_non_conforming_reply_is_quarantined_not_raised() -> None:
    handler = httpx.MockTransport(lambda request: _chat_response({"unexpected": "shape"}))
    posting = make_posting()
    verdict = classify_llm(
        posting,
        description=_LONG_DESCRIPTION,
        timeout_s=5,
        base_url=_BASE_URL,
        model=_MODEL,
        max_description_chars=6000,
        client=httpx.Client(transport=handler),
    )
    assert verdict is None


def test_server_busy_returns_none_with_no_fallback() -> None:
    handler = httpx.MockTransport(lambda request: httpx.Response(503))
    posting = make_posting()
    verdict = classify_llm(
        posting,
        description=_LONG_DESCRIPTION,
        timeout_s=5,
        base_url=_BASE_URL,
        model=_MODEL,
        max_description_chars=6000,
        client=httpx.Client(transport=handler),
    )
    assert verdict is None


def test_server_down_returns_none_and_the_run_continues() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    posting = make_posting()
    # classify_llm must swallow this itself — the contract is `LlmVerdict | None`,
    # never an exception (blueprint/03-INTERFACES.md §3.3).
    verdict = classify_llm(
        posting,
        description=_LONG_DESCRIPTION,
        timeout_s=5,
        base_url=_BASE_URL,
        model=_MODEL,
        max_description_chars=6000,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert verdict is None


def test_connect_error_is_internally_an_llm_unavailable() -> None:
    """White-box: the internal exception class exists and is what a down server raises."""
    from jobtracker.match.llm import _post_completion

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(LlmUnavailable):
        _post_completion(
            httpx.Client(transport=httpx.MockTransport(handler)),
            base_url=_BASE_URL,
            payload={},
            timeout_s=5,
        )


def test_timeout_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    posting = make_posting()
    verdict = classify_llm(
        posting,
        description=_LONG_DESCRIPTION,
        timeout_s=5,
        base_url=_BASE_URL,
        model=_MODEL,
        max_description_chars=6000,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert verdict is None


def test_concurrency_never_exceeds_one_under_load() -> None:
    in_flight = 0
    max_in_flight = 0
    lock = threading.Lock()

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        return _chat_response(
            {
                "role_family": "quant_dev",
                "seniority": "junior",
                "min_years": None,
                "visa_sponsorship": "unknown",
                "phd_required": False,
                "confidence": 0.9,
            }
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    posting = make_posting()

    def call() -> None:
        classify_llm(
            posting,
            description=_LONG_DESCRIPTION,
            timeout_s=5,
            base_url=_BASE_URL,
            model=_MODEL,
            max_description_chars=6000,
            client=client,
        )

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_in_flight == 1


def test_apply_llm_verdict_sets_resolver_stage_to_llm() -> None:
    posting = make_posting(role_family=RoleFamily.OTHER, resolver_stage="rules")
    llm_verdict = LlmVerdict(
        role_family=RoleFamily.QUANT_DEV,
        seniority=Seniority.JUNIOR,
        min_years=1,
        visa_sponsorship=VisaStatus.SPONSORS,
        phd_required=False,
        confidence=0.9,
    )
    updated = apply_llm_verdict(posting, llm_verdict)
    assert updated.role_family == RoleFamily.QUANT_DEV
    assert updated.resolver_stage == "llm"
    assert posting.resolver_stage == "rules"  # the original is untouched


def test_resolve_residual_skips_the_call_when_llm_is_disabled(
    settings_factory: Callable[..., Settings],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("classify_llm must not be called when JT_LLM_ENABLED=false")

    posting = make_posting(seniority=Seniority.UNKNOWN)
    verdict = make_verdict(score=50, tier=Tier.POSSIBLE)
    profile = _profile()
    settings = settings_factory(**{**_LLM_ON, "llm_enabled": False})
    result = resolve_residual(
        posting, verdict, profile=profile, settings=settings, description=_LONG_DESCRIPTION
    )
    assert result is verdict


def test_resolve_residual_skips_the_call_when_not_ambiguous(
    settings_factory: Callable[..., Settings],
) -> None:
    posting = make_posting(seniority=Seniority.JUNIOR, visa_sponsorship=VisaStatus.SPONSORS)
    verdict = make_verdict(score=95, tier=Tier.STRONG)
    result = resolve_residual(
        posting,
        verdict,
        profile=_profile(),
        settings=settings_factory(**_LLM_ON),
        description=_LONG_DESCRIPTION,
    )
    assert result is verdict


def test_resolve_residual_keeps_the_deterministic_verdict_on_low_confidence(
    settings_factory: Callable[..., Settings],
) -> None:
    handler = httpx.MockTransport(
        lambda request: _chat_response(
            {
                "role_family": "quant_dev",
                "seniority": "junior",
                "min_years": 1,
                "visa_sponsorship": "sponsors",
                "phd_required": False,
                "confidence": 0.2,
            }
        )
    )
    posting = make_posting(seniority=Seniority.UNKNOWN, resolver_stage="rules")
    verdict = make_verdict(score=50, tier=Tier.POSSIBLE)

    result = resolve_residual(
        posting,
        verdict,
        profile=_profile(),
        settings=settings_factory(**_LLM_ON),
        description=_LONG_DESCRIPTION,
        client=httpx.Client(transport=handler),
    )
    assert result is verdict  # quarantined: never promoted on low confidence


def test_resolve_residual_promotes_and_rescores_on_a_confident_reply(
    settings_factory: Callable[..., Settings],
) -> None:
    handler = httpx.MockTransport(
        lambda request: _chat_response(
            {
                "role_family": "quant_dev",
                "seniority": "junior",
                "min_years": 1,
                "visa_sponsorship": "sponsors",
                "phd_required": False,
                "confidence": 0.95,
            }
        )
    )
    posting = make_posting(
        seniority=Seniority.UNKNOWN,
        visa_sponsorship=VisaStatus.UNKNOWN,
        resolver_stage="rules",
        role_family=RoleFamily.QUANT_DEV,
    )
    verdict = make_verdict(score=20, tier=Tier.STRETCH)

    result = resolve_residual(
        posting,
        verdict,
        profile=_profile(),
        settings=settings_factory(**_LLM_ON),
        description=_LONG_DESCRIPTION,
        client=httpx.Client(transport=handler),
    )
    assert result != verdict
    assert result.score != verdict.score  # recomputed by match.score, not copied from the LLM


def test_grep_no_remote_llm_api_fallback() -> None:
    """ADR-010, verified exactly the way the acceptance criterion says: by grep."""
    source = (
        Path(__file__).resolve().parent.parent / "src" / "jobtracker" / "match" / "llm.py"
    ).read_text(encoding="utf-8")
    forbidden = [
        "openai.com",
        "anthropic.com",
        "api.mistral.ai",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ]
    hits = [needle for needle in forbidden if needle.lower() in source.lower()]
    assert not hits, f"remote LLM fallback markers found in match/llm.py: {hits}"
