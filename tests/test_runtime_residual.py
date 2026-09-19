"""The LLM residual lane end to end — blueprint/wp/WP12-match-llm.md §4.1, §5.

No real network: the LLM is an `httpx.MockTransport` we can switch on and off,
which is the whole point — the server is *not always up*, and every test below
is about what the pipeline does when it isn't.
"""

import json
import sqlite3
from datetime import UTC, datetime

import httpx
import pytest

from factories_store import make_board
from jobtracker.core.enums import Source, Tier
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import RawPosting
from jobtracker.match.profile import Profile, build_profile
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.runtime.pipeline import ingest
from jobtracker.runtime.residual import (
    EntryResult,
    LlmClientConfig,
    drain_all,
    drain_queue,
    enqueue_backlog,
    process_entry,
)
from jobtracker.store import llm_queue
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import get_posting, get_verdict

pytestmark = pytest.mark.db

_PROFILE_DATA = {
    "version": 1,
    "titles": {"strong": ["quant developer"], "possible": ["software engineer"], "excluded": []},
    "seniority": {"accept_if_years_max": 3, "reject": ["senior", "lead"]},
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
    "review": {
        "version": 1,
        "override_confidence": 0.8,
        "evidence_min_chars": 6,
        "max_locations": 8,
        "max_per_collect": 300,
        "max_output_tokens": 1200,
        "max_description_chars": 12000,
        "salary_bounds": {
            "year": [10000, 10000000],
            "month": [500, 500000],
            "day": [20, 20000],
            "hour": [5, 5000],
        },
        "currencies": ["USD", "EUR", "GBP", "CHF", "SGD", "HKD"],
    },
}
_DESCRIPTION = "We build low latency trading systems and need an engineer to join the desk. " * 4
_GOOD_REPLY = {
    "role_family": "quant_dev",
    "seniority": "graduate",
    "min_years": 0,
    "visa_sponsorship": "sponsors",
    "phd_required": False,
    "confidence": 0.95,
}


class FakeLlm:
    """A switchable llama-server: up with a canned reply, busy (503), or down."""

    def __init__(self) -> None:
        self.mode = "up"
        self.reply: dict[str, object] | str = _GOOD_REPLY
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.mode == "down":
            raise httpx.ConnectError("connection refused", request=request)
        if self.mode == "busy":
            return httpx.Response(503)
        content = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    def config(self) -> LlmClientConfig:
        return LlmClientConfig(
            base_url="http://llm.invalid/v1",
            model="m",
            drain_timeout_s=5,
            client=httpx.Client(transport=httpx.MockTransport(self.handler)),
        )


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm()


@pytest.fixture
def profile() -> Profile:
    return build_profile(_PROFILE_DATA, company_tiers={"acme": 1})


@pytest.fixture(autouse=True)
def _company(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    store_conn.commit()


def _raw(title: str, *, content_hash: str = "h1") -> RawPosting:
    return RawPosting(
        source=Source.GREENHOUSE,
        company_slug="acme",
        source_job_id=title,
        url=f"https://example.com/{title}",
        title_raw=title,
        description_raw=_DESCRIPTION,
        location_raw="New York, USA",
        department_raw=None,
        posted_at_raw=None,
        payload=b"{}",
        fetched_at=datetime.now(UTC),
        content_hash=content_hash,
    )


def _ingest(  # noqa: PLR0917 — one positional per collaborator keeps call sites short
    conn: sqlite3.Connection,
    raw: RawPosting,
    taxonomy: Taxonomy,
    geo: GeoIndex,
    profile: Profile,
    cfg: LlmClientConfig | None,
) -> str:
    result = ingest(
        conn, raw, taxonomy=taxonomy, geo=geo, profile=profile, hq_country="US", llm=cfg
    )
    assert result.posting_id is not None
    return result.posting_id


# "Software Engineer" at a rank-1 company: seniority unknown -> ambiguous, but at
# score 36 not close enough to strong to be urgent — it waits for the drain.
_DEFERRED = "Software Engineer"
# "Executive Assistant" is `not_quant`, and at a rank-1 company that is exactly the
# rejection the LLM exists to overturn — ambiguous *and* urgent.
_URGENT = "Executive Assistant"


def test_llm_disabled_never_queues_anything(
    store_conn: sqlite3.Connection, taxonomy: Taxonomy, geo_index: GeoIndex, profile: Profile
) -> None:
    _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, None)
    assert llm_queue.depth(store_conn) == 0


def test_an_ambiguous_posting_is_queued_and_keeps_its_deterministic_verdict(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    posting_id = _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, llm.config())
    assert llm_queue.depth(store_conn) == 1
    assert llm.calls == 0  # not urgent: no attempt at ingest time
    verdict = get_verdict(store_conn, posting_id)
    assert verdict is not None and verdict.tier == Tier.STRETCH


def test_a_posting_the_prefilter_screens_out_is_never_queued(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    _ingest(store_conn, _raw("Quantitative Developer"), taxonomy, geo_index, profile, llm.config())
    assert llm_queue.depth(store_conn) == 0  # low_score rejection: nothing an LLM could change


def test_an_unchanged_refetch_does_not_requeue(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    posting_id = _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, cfg)
    assert drain_queue(store_conn, profile=profile, cfg=cfg).resolved == 1

    _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, cfg)  # same content_hash
    assert llm_queue.depth(store_conn) == 0
    stored = get_posting(store_conn, posting_id)
    assert stored is not None and stored.resolver_stage == "llm"  # the resolution survived


def test_server_down_requeues_with_attempts_and_no_fallback(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    posting_id = _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, cfg)
    before = get_verdict(store_conn, posting_id)

    llm.mode = "down"
    for turn in (1, 2):
        result = drain_queue(store_conn, profile=profile, cfg=cfg)
        assert (result.requeued, result.resolved, result.server_available) == (1, 0, False)
        entry = llm_queue.get_entry(store_conn, posting_id)
        assert entry is not None and entry.attempts == turn  # attempts += 1 per skipped turn

    assert get_verdict(store_conn, posting_id) == before  # the run carried on, verdict intact


def test_server_busy_requeues_too(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, cfg)
    llm.mode = "busy"
    assert drain_queue(store_conn, profile=profile, cfg=cfg).requeued == 1
    assert llm_queue.depth(store_conn) == 1


def test_a_drain_stops_at_the_first_unavailable_server(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    _ingest(store_conn, _raw("Software Engineer"), taxonomy, geo_index, profile, cfg)
    _ingest(store_conn, _raw("Software Engineer II"), taxonomy, geo_index, profile, cfg)
    llm.mode = "down"
    drain_queue(store_conn, profile=profile, cfg=cfg)
    assert llm.calls == 1  # one refused call, not one per queued posting


def test_the_server_coming_back_up_drains_the_backlog_and_rescores(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    posting_id = _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, cfg)
    before = get_verdict(store_conn, posting_id)
    assert before is not None

    llm.mode = "down"
    drain_queue(store_conn, profile=profile, cfg=cfg)
    llm.mode = "up"
    result = drain_queue(store_conn, profile=profile, cfg=cfg)

    assert (result.resolved, result.remaining) == (1, 0)
    posting = get_posting(store_conn, posting_id)
    after = get_verdict(store_conn, posting_id)
    assert posting is not None and after is not None
    assert posting.resolver_stage == "llm"
    assert posting.seniority.value == "graduate"
    assert after.score > before.score  # recomputed by match.score from the new fields
    assert any(r.code == "graduate_programme" for r in after.reasons)  # ...and explainable
    stored = store_conn.execute("SELECT score, tier FROM postings").fetchone()
    assert (stored["score"], stored["tier"]) == (after.score, after.tier.value)


def test_a_non_conforming_reply_is_quarantined_without_retry(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    posting_id = _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, cfg)
    before = get_verdict(store_conn, posting_id)
    llm.reply = {"unexpected": "shape"}

    result = drain_queue(store_conn, profile=profile, cfg=cfg)
    assert (result.quarantined, result.remaining) == (1, 0)
    assert get_verdict(store_conn, posting_id) == before


def test_an_under_confident_reply_is_quarantined_not_promoted(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    posting_id = _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, cfg)
    before = get_verdict(store_conn, posting_id)
    llm.reply = {**_GOOD_REPLY, "confidence": 0.2}

    assert drain_queue(store_conn, profile=profile, cfg=cfg).quarantined == 1
    assert get_verdict(store_conn, posting_id) == before
    posting = get_posting(store_conn, posting_id)
    assert posting is not None and posting.resolver_stage == "rules"


def test_an_urgent_posting_gets_one_immediate_attempt_at_ingest(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    posting_id = _ingest(store_conn, _raw(_URGENT), taxonomy, geo_index, profile, llm.config())
    assert llm.calls == 1
    assert llm_queue.depth(store_conn) == 0  # resolved on the spot
    posting = get_posting(store_conn, posting_id)
    assert posting is not None and posting.resolver_stage == "llm"
    assert posting.role_family.value == "quant_dev"  # the not_quant rejection overturned


def test_an_urgent_posting_stays_queued_when_the_server_is_down_then_cools_down(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    llm.mode = "down"
    _ingest(store_conn, _raw(_URGENT), taxonomy, geo_index, profile, cfg)
    assert (llm.calls, llm_queue.depth(store_conn)) == (1, 1)

    _ingest(store_conn, _raw("Office Manager"), taxonomy, geo_index, profile, cfg)
    entry_ids = [e.posting_id for e in llm_queue.pending(store_conn, 10)]
    # The second urgent posting is queued but does not stall ingest on a server
    # that just refused us: no second attempt inside the cooldown window.
    assert llm.calls == 1
    assert len(entry_ids) == 2


def test_process_entry_drops_a_deactivated_posting(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    posting_id = _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, cfg)
    store_conn.execute("UPDATE postings SET is_active = 0 WHERE posting_id = ?", (posting_id,))
    store_conn.commit()

    result = process_entry(store_conn, posting_id, profile=profile, cfg=cfg, timeout_s=5)
    assert result == EntryResult.DROPPED
    assert (llm.calls, llm_queue.depth(store_conn)) == (0, 0)


def test_concurrency_stays_at_one_call_per_turn(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    for title in ("Software Engineer", "Software Engineer II", "Software Engineer III"):
        _ingest(store_conn, _raw(title), taxonomy, geo_index, profile, cfg)
    assert drain_queue(store_conn, profile=profile, cfg=cfg).resolved == 3
    assert llm.calls == 3  # strictly sequential: the module-level guard is never contended


def test_the_backlog_catch_up_queues_what_ingest_never_saw(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    # Collected while the LLM was off: stored, ambiguous, and never queued.
    ambiguous = _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, None)
    _ingest(
        store_conn,
        _raw("Quantitative Developer", content_hash="h2"),
        taxonomy,
        geo_index,
        profile,
        None,
    )
    assert llm_queue.depth(store_conn) == 0

    assert enqueue_backlog(store_conn, profile=profile) >= 1

    assert llm_queue.get_entry(store_conn, ambiguous) is not None
    assert enqueue_backlog(store_conn, profile=profile) == 0  # idempotent: nothing new to add
    assert llm.calls == 0  # filling the queue never touches the server


def test_a_backlog_posting_the_llm_already_settled_is_not_queued_again(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    _ingest(store_conn, _raw(_DEFERRED), taxonomy, geo_index, profile, cfg)
    drain_queue(store_conn, profile=profile, cfg=cfg)
    assert llm_queue.depth(store_conn) == 0

    assert enqueue_backlog(store_conn, profile=profile) == 0


def test_drain_all_clears_more_than_one_batch(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    for i in range(5):
        _ingest(
            store_conn,
            _raw(f"Software Engineer {i}", content_hash=f"h{i}"),
            taxonomy,
            geo_index,
            profile,
            llm.config(),
        )
    assert llm_queue.depth(store_conn) == 5
    batches: list[int] = []

    result = drain_all(
        store_conn,
        profile=profile,
        cfg=llm.config(),
        batch_size=2,
        on_batch=lambda r: batches.append(r.remaining),
    )

    assert result.resolved == 5 and result.remaining == 0
    assert batches == [3, 1, 0]  # three passes of at most two, reported as they went


def test_drain_all_stops_when_the_server_goes_away(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    cfg = llm.config()
    for i in range(3):
        _ingest(
            store_conn,
            _raw(f"Software Engineer {i}", content_hash=f"h{i}"),
            taxonomy,
            geo_index,
            profile,
            cfg,
        )
    llm.mode = "down"

    result = drain_all(store_conn, profile=profile, cfg=cfg)

    assert result.server_available is False
    assert result.remaining == 3  # nothing lost, nothing hammered
    assert llm.calls == 1
