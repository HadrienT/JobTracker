"""The residual LLM call — blueprint/wp/WP12-match-llm.md §4, ADR-006, ADR-010.

The **only** module in `match` allowed to open a socket (blueprint/01-ARCHITECTURE.md
§2, contract D8): `match.prefilter`, `match.rules` and `match.score` stay
pure and rejouable offline, and this file is where the one documented
exception lives, isolated so it shows up in a diff.

Two rules govern every call here, both non-negotiable:

- **Concurrency 1, no remote fallback** (ADR-010). `llama-server` is shared
  with OpenHands; a busy or unreachable server is a skipped turn, never an
  error and never a reason to call out to a hosted API.
- **The LLM fills fields, never a score** (ADR-006). `classify_llm` returns
  `LlmVerdict` — the same fields `normalize` would have produced — and
  `match.score.evaluate` recomputes the score from them, so a score is always
  reproducible from its `Reason`s alone.
"""

import json as jsonlib
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from jobtracker.core.config import Settings
from jobtracker.core.enums import RoleFamily, Seniority, VisaStatus
from jobtracker.core.errors import LlmUnavailable
from jobtracker.core.logging import get_logger
from jobtracker.core.models import MatchVerdict, Posting
from jobtracker.match.prefilter import is_ambiguous
from jobtracker.match.profile import Profile
from jobtracker.match.score import evaluate

_logger = get_logger(__name__)

# Concurrency côté JobTracker : jamais plus d'un appel en vol, y compris quand
# deux sources tournent en parallèle (blueprint/wp/WP08-runtime.md §3) et
# tombent toutes les deux sur une offre ambiguë au même instant. Un
# `acquire(blocking=False)` qui échoue est traité exactement comme un serveur
# occupé : un tour sauté, jamais une file d'attente qui bloquerait le thread.
_concurrency_guard = threading.Lock()

_SYSTEM_PROMPT = """\
You classify a single job posting for a quantitative-finance job feed. \
Answer only with the requested fields, matching the given JSON schema exactly.

Rules:
- Never guess. A field you cannot determine is "unknown" (or null for min_years).
- visa_sponsorship="no" ONLY if the text excludes sponsorship or requires a \
pre-existing right to work. "We are unable to sponsor visas" is a "no".
- A location restriction such as "Remote, US only" counts as "no" for a candidate \
who does not already hold that right to work.
- If the text says nothing about visas, the answer is "unknown". It is not "no".
- min_years is the minimum REQUIRED, never the top of a stated range.
- "PhD preferred" is NOT phd_required. Neither is "PhD or equivalent experience".
- A "Software Engineer" title at a trading firm is quant_dev or swe_platform \
depending on the description, never "other".
"""


class LlmVerdict(BaseModel, frozen=True, extra="forbid"):
    """Fields, not a score (ADR-006) — `match.score.evaluate` recomputes the score."""

    role_family: RoleFamily
    seniority: Seniority
    min_years: int | None
    visa_sponsorship: VisaStatus
    phd_required: bool
    confidence: float = Field(ge=0.0, le=1.0)


def _user_content(posting: Posting, description: str, *, max_description_chars: int) -> str:
    return (
        f"Company: {posting.company_slug}\n"
        f"Title: {posting.title_raw}\n"
        f"Already resolved (uncertain fields are 'unknown'): "
        f"role_family={posting.role_family.value}, seniority={posting.seniority.value}, "
        f"min_years={posting.min_years}, visa_sponsorship={posting.visa_sponsorship.value}, "
        f"phd_required={posting.phd_required}\n\n"
        f"Description:\n{description[:max_description_chars]}"
    )


def _build_payload(
    posting: Posting, description: str, *, model: str, max_description_chars: int
) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _user_content(
                    posting, description, max_description_chars=max_description_chars
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "llm_verdict",
                "schema": LlmVerdict.model_json_schema(),
                "strict": True,
            },
        },
    }


def _post_completion(
    client: httpx.Client, *, base_url: str, payload: dict[str, Any], timeout_s: int
) -> httpx.Response:
    try:
        return client.post(f"{base_url}/chat/completions", json=payload, timeout=timeout_s)
    except httpx.ConnectError as exc:
        raise LlmUnavailable(f"llama-server unreachable at {base_url}") from exc


def _extract_verdict(response: httpx.Response, *, posting_id: str) -> LlmVerdict | None:
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        data = jsonlib.loads(content)
        return LlmVerdict.model_validate(data)
    except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
        # Non-conforming output: rejected, quarantine, never an alert (§4.2) —
        # a malformed reply is treated exactly like low confidence, not a crash.
        _logger.warning("llm_response_non_conforming", posting_id=posting_id, error=str(exc))
        return None


class LlmStatus(StrEnum):
    OK = "ok"
    # Busy, unreachable, timed out, or another call already in flight here: the
    # posting should be tried again later.
    UNAVAILABLE = "unavailable"
    # The server answered but not with a schema-conforming verdict: retrying the
    # same prompt is pointless, the posting is quarantined instead.
    NON_CONFORMING = "non_conforming"


@dataclass(frozen=True)
class LlmOutcome:
    status: LlmStatus
    verdict: LlmVerdict | None = None


def attempt_llm(
    posting: Posting,
    *,
    description: str,
    timeout_s: int,
    base_url: str,
    model: str,
    max_description_chars: int,
    client: httpx.Client | None = None,
) -> LlmOutcome:
    """Same call as `classify_llm`, but says *why* there was no verdict.

    The queue needs the distinction `None` erases: an unavailable server means
    "requeue and try next turn", a malformed reply means "quarantine". Never
    raises, for the same reason `classify_llm` never does.
    """
    if not _concurrency_guard.acquire(blocking=False):
        _logger.info("llm_skipped_local_concurrency", posting_id=posting.posting_id)
        return LlmOutcome(LlmStatus.UNAVAILABLE)
    try:
        owned_client = client is None
        http_client = client if client is not None else httpx.Client()
        try:
            payload = _build_payload(
                posting, description, model=model, max_description_chars=max_description_chars
            )
            response = _post_completion(
                http_client, base_url=base_url, payload=payload, timeout_s=timeout_s
            )
        except LlmUnavailable:
            _logger.warning("llm_unavailable", posting_id=posting.posting_id, base_url=base_url)
            return LlmOutcome(LlmStatus.UNAVAILABLE)
        except httpx.TimeoutException:
            _logger.info("llm_skipped_busy_timeout", posting_id=posting.posting_id)
            return LlmOutcome(LlmStatus.UNAVAILABLE)
        finally:
            if owned_client:
                http_client.close()

        if response.status_code != httpx.codes.OK:
            _logger.info(
                "llm_skipped_busy_status",
                posting_id=posting.posting_id,
                status=response.status_code,
            )
            return LlmOutcome(LlmStatus.UNAVAILABLE)

        verdict = _extract_verdict(response, posting_id=posting.posting_id)
        if verdict is None:
            return LlmOutcome(LlmStatus.NON_CONFORMING)
        return LlmOutcome(LlmStatus.OK, verdict)
    finally:
        _concurrency_guard.release()


def classify_llm(
    posting: Posting,
    *,
    description: str,
    timeout_s: int,
    base_url: str,
    model: str,
    max_description_chars: int,
    client: httpx.Client | None = None,
) -> LlmVerdict | None:
    """`None` means "indisponible" — busy, unreachable, or a non-conforming reply.

    Never raises: every failure mode this function can hit is, by design
    (blueprint/wp/WP12-match-llm.md §4.1), a skipped turn rather than an error
    the caller has to handle. `client` exists only for tests (a real `httpx.Client`
    is opened otherwise) — mirrors `collect.http.PolicedHttpSession`'s own seam.
    """
    return attempt_llm(
        posting,
        description=description,
        timeout_s=timeout_s,
        base_url=base_url,
        model=model,
        max_description_chars=max_description_chars,
        client=client,
    ).verdict


def apply_llm_verdict(posting: Posting, llm_verdict: LlmVerdict) -> Posting:
    """Pure field merge — no I/O, safe to call outside `match.llm` too.

    `is_ambiguous` only ever sends a posting here because the rules already
    failed to pin these fields down, so the LLM's answer replaces them
    outright rather than being reconciled field by field.
    """
    return posting.model_copy(
        update={
            "role_family": llm_verdict.role_family,
            "seniority": llm_verdict.seniority,
            "min_years": llm_verdict.min_years,
            "visa_sponsorship": llm_verdict.visa_sponsorship,
            "phd_required": llm_verdict.phd_required,
            "resolver_stage": "llm",
        }
    )


def rescore_with_llm(
    posting: Posting, llm_verdict: LlmVerdict, *, profile: Profile
) -> tuple[Posting, MatchVerdict] | None:
    """Apply the LLM's fields and recompute the score — `None` if under-confident.

    `None` is the quarantine: below `profile.llm.min_confidence` the posting keeps
    its deterministic verdict rather than being promoted on a guess (§4.3).
    """
    if llm_verdict.confidence < profile.llm.min_confidence:
        return None
    updated = apply_llm_verdict(posting, llm_verdict)
    return updated, evaluate(updated, profile=profile)


def resolve_residual(
    posting: Posting,
    verdict: MatchVerdict,
    *,
    profile: Profile,
    settings: Settings,
    description: str,
    client: httpx.Client | None = None,
) -> MatchVerdict:
    """The end-to-end residual path: prefilter, call, confidence gate, rescore.

    Returns `verdict` unchanged whenever there is nothing to do — LLM
    disabled, not ambiguous, the server was unavailable, or the reply came
    back under-confident. This is the function `runtime` will eventually call
    from `pipeline.ingest`; it is not wired in yet (blueprint/dependencies.md
    scopes that wiring to a later work package), but it is the complete,
    independently-tested contract for when it is. `client` is the same test
    seam as `classify_llm`'s.
    """
    if not settings.llm_enabled:
        return verdict
    if not is_ambiguous(posting, verdict, profile=profile, description=description):
        return verdict

    llm_verdict = classify_llm(
        posting,
        description=description,
        timeout_s=settings.llm_timeout_s,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        max_description_chars=profile.llm.max_description_chars,
        client=client,
    )
    if llm_verdict is None:
        return verdict
    rescored = rescore_with_llm(posting, llm_verdict, profile=profile)
    return verdict if rescored is None else rescored[1]
