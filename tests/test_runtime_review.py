"""The LLM re-read end to end — blueprint/wp/WP19-llm-review.md.

The server is an `httpx.MockTransport` that answers with a canned reading. What is under test is
everything around the model: that a correction is written with its audit trail, that a dry run
writes nothing, that a stopped server ends the run cleanly, and that nothing the model changed is
undone by the next replay.
"""

import json
import sqlite3
from decimal import Decimal

import httpx
import pytest

from factories_store import make_board
from jobtracker.core.clock import utc_now
from jobtracker.core.enums import Source
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import RawPosting
from jobtracker.match.profile import Profile, build_profile
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.runtime import replay
from jobtracker.runtime.pipeline import ingest
from jobtracker.runtime.residual import LlmClientConfig
from jobtracker.runtime.review import review_all, review_posting
from jobtracker.store import llm_reviews
from jobtracker.store.companies import sync_companies
from jobtracker.store.postings import get_posting, get_verdict
from test_runtime_pipeline import _PROFILE_DATA

pytestmark = pytest.mark.db

_DESCRIPTION = (
    "We build low latency trading systems and are hiring a Quantitative Developer. "
    "Base pay: GBP 120k-160k p.a. for this role, plus a discretionary bonus. "
    "You will need at least 3 years of experience in C++. "
    "Work permit assistance will be provided for the right candidate. "
) * 2
_SALARY_QUOTE = "Base pay: GBP 120k-160k p.a. for this role"


def _reading(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "compensation": {
            "amount_min": "120000",
            "amount_max": "160000",
            "currency": "GBP",
            "period": "year",
            "evidence": _SALARY_QUOTE,
        },
        "locations": [],
        "seniority": "unknown",
        "min_years": None,
        "seniority_evidence": None,
        "visa_sponsorship": "sponsors",
        "visa_evidence": "Work permit assistance will be provided for the right candidate",
        "phd_required": False,
        "phd_evidence": None,
        "closes_at": None,
        "closes_evidence": None,
        "confidence": 0.95,
    }
    base.update(overrides)
    return base


class FakeLlm:
    def __init__(self) -> None:
        self.mode = "up"
        self.reading: dict[str, object] | str = _reading()
        self.calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.mode == "down":
            raise httpx.ConnectError("refused", request=request)
        content = self.reading if isinstance(self.reading, str) else json.dumps(self.reading)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    def config(self) -> LlmClientConfig:
        return LlmClientConfig(
            base_url="http://llm.invalid/v1",
            model="test-model",
            drain_timeout_s=5,
            client=httpx.Client(transport=httpx.MockTransport(self.handler)),
        )


@pytest.fixture
def llm() -> FakeLlm:
    return FakeLlm()


@pytest.fixture
def profile() -> Profile:
    return build_profile(_PROFILE_DATA)


@pytest.fixture(autouse=True)
def _company(store_conn: sqlite3.Connection) -> None:
    sync_companies(store_conn, [make_board()])
    store_conn.commit()


def _ingest(
    conn, taxonomy, geo, profile, *, title="Quantitative Developer", content_hash="h1", job="j1"
) -> str:
    raw = RawPosting(
        source=Source.GREENHOUSE,
        company_slug="acme",
        source_job_id=job,
        url=f"https://example.com/{job}",
        title_raw=title,
        description_raw=_DESCRIPTION,
        location_raw="London",
        department_raw=None,
        posted_at_raw=None,
        payload=b"{}",
        fetched_at=utc_now(),  # fresh: a stale posting is rejected and carries no reasons
        content_hash=content_hash,
    )
    result = ingest(conn, raw, taxonomy=taxonomy, geo=geo, profile=profile, hq_country="GB")
    assert result.posting_id is not None
    return result.posting_id


def _salary(conn: sqlite3.Connection, posting_id: str):
    row = conn.execute(
        "SELECT salary_min, salary_max, salary_currency, salary_period FROM postings "
        "WHERE posting_id = ?",
        (posting_id,),
    ).fetchone()
    return tuple(row)


def test_a_correction_is_written_with_its_audit_trail_and_the_score_follows(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    posting_id = _ingest(store_conn, taxonomy, geo_index, profile)
    assert _salary(store_conn, posting_id) == (None, None, None, None)  # the rules missed it
    unread = get_posting(store_conn, posting_id)
    assert unread is not None and unread.visa_sponsorship.value == "unknown"  # ...and this too
    before = get_verdict(store_conn, posting_id)
    assert before is not None

    stats = review_all(store_conn, profile=profile, geo=geo_index, cfg=llm.config())

    assert (stats.read, stats.corrected) == (1, 1)
    low, high, currency, period = _salary(store_conn, posting_id)
    assert (Decimal(low), Decimal(high), currency, period) == (
        Decimal("120000"),
        Decimal("160000"),
        "GBP",
        "year",
    )
    posting = get_posting(store_conn, posting_id)
    assert posting is not None
    assert posting.visa_sponsorship.value == "sponsors"
    assert posting.resolver_stage == "llm"
    after = get_verdict(store_conn, posting_id)
    assert after is not None
    assert any(r.code == "salary_disclosed" for r in after.reasons)  # the score follows the fields

    corrections = llm_reviews.list_corrections(
        store_conn, posting_id, content_hash=posting.content_hash
    )
    assert {c.field for c in corrections} == {"compensation", "visa_sponsorship"}
    salary = next(c for c in corrections if c.field == "compensation")
    assert salary.before["amount_min"] is None
    assert salary.after["amount_min"] == "120000"
    assert salary.evidence == _SALARY_QUOTE
    assert stats.corrections_by_field["compensation"] == 1


def test_a_dry_run_says_what_it_would_do_and_writes_nothing(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    posting_id = _ingest(store_conn, taxonomy, geo_index, profile)

    stats = review_all(store_conn, profile=profile, geo=geo_index, cfg=llm.config(), dry_run=True)

    assert stats.corrected == 1
    assert _salary(store_conn, posting_id) == (None, None, None, None)
    assert store_conn.execute("SELECT COUNT(*) FROM llm_reviews").fetchone()[0] == 0
    assert store_conn.execute("SELECT COUNT(*) FROM llm_corrections").fetchone()[0] == 0


def test_a_hallucinated_reading_changes_nothing_and_says_why(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    posting_id = _ingest(store_conn, taxonomy, geo_index, profile)
    llm.reading = _reading(
        compensation={
            "amount_min": "300000",
            "amount_max": "400000",
            "currency": "GBP",
            "period": "year",
            "evidence": "The base salary is GBP 300k-400k per year",
        },
        visa_sponsorship="unknown",
        visa_evidence=None,
    )

    stats = review_all(store_conn, profile=profile, geo=geo_index, cfg=llm.config())

    assert (stats.confirmed, stats.corrected) == (1, 0)
    assert _salary(store_conn, posting_id) == (None, None, None, None)
    assert any("not in the posting" in reason for reason in stats.refused)


def test_a_read_posting_is_not_read_again_until_its_content_or_the_prompt_changes(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    posting_id = _ingest(store_conn, taxonomy, geo_index, profile)
    review_all(store_conn, profile=profile, geo=geo_index, cfg=llm.config())
    calls = llm.calls

    assert llm_reviews.unreviewed_posting_ids(store_conn, review_version=1) == []
    review_all(store_conn, profile=profile, geo=geo_index, cfg=llm.config())
    assert llm.calls == calls  # nothing to read

    # A new prompt version reads everything again.
    assert llm_reviews.unreviewed_posting_ids(store_conn, review_version=2) == [posting_id]
    # So does a re-fetch whose content changed.
    _ingest(store_conn, taxonomy, geo_index, profile, content_hash="h2")
    assert llm_reviews.unreviewed_posting_ids(store_conn, review_version=1) == [posting_id]


def test_a_stopped_server_ends_the_run_cleanly_and_the_next_one_resumes(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    for i in range(3):
        _ingest(
            store_conn,
            taxonomy,
            geo_index,
            profile,
            title=f"Quant Dev {i}",
            job=f"j{i}",
            content_hash=f"h{i}",
        )
    llm.mode = "down"

    stopped = review_all(store_conn, profile=profile, geo=geo_index, cfg=llm.config())

    assert stopped.server_available is False
    assert stopped.read == 0
    assert llm.calls == 1  # one refused turn, no hammering
    assert len(llm_reviews.unreviewed_posting_ids(store_conn, review_version=1)) == 3

    llm.mode = "up"
    resumed = review_all(store_conn, profile=profile, geo=geo_index, cfg=llm.config())
    assert resumed.read == 3


def test_a_non_conforming_reply_is_set_aside_not_retried_forever(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    posting_id = _ingest(store_conn, taxonomy, geo_index, profile)
    llm.reading = "not json at all"

    stats = review_all(store_conn, profile=profile, geo=geo_index, cfg=llm.config())

    assert stats.set_aside == 1
    row = store_conn.execute(
        "SELECT outcome FROM llm_reviews WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    assert row["outcome"] == "set_aside"
    assert llm_reviews.unreviewed_posting_ids(store_conn, review_version=1) == []


def test_limit_and_a_single_posting(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    ids = [
        _ingest(
            store_conn,
            taxonomy,
            geo_index,
            profile,
            title=f"Quant Dev {i}",
            job=f"j{i}",
            content_hash=f"h{i}",
        )
        for i in range(4)
    ]

    limited = review_all(store_conn, profile=profile, geo=geo_index, cfg=llm.config(), limit=2)
    only = review_all(
        store_conn, profile=profile, geo=geo_index, cfg=llm.config(), posting_ids=[ids[3]]
    )

    assert limited.read == 2
    assert only.read == 1


def test_an_inactive_posting_is_skipped(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    posting_id = _ingest(store_conn, taxonomy, geo_index, profile)
    store_conn.execute("UPDATE postings SET is_active = 0 WHERE posting_id = ?", (posting_id,))
    store_conn.commit()

    step = review_posting(
        store_conn, posting_id, profile=profile, geo=geo_index, cfg=llm.config(), dry_run=False
    )

    assert step is None
    assert llm.calls == 0


def test_a_replay_does_not_put_back_what_the_text_contradicted(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    posting_id = _ingest(store_conn, taxonomy, geo_index, profile)
    review_all(store_conn, profile=profile, geo=geo_index, cfg=llm.config())
    assert _salary(store_conn, posting_id)[0] is not None

    report = replay.run_replay(
        store_conn, taxonomy=taxonomy, geo=geo_index, profile=profile, apply=True
    )

    assert report.applied
    assert Decimal(_salary(store_conn, posting_id)[0]) == Decimal("120000")  # kept
    posting = get_posting(store_conn, posting_id)
    assert posting is not None
    assert posting.visa_sponsorship.value == "sponsors"


def test_a_corrected_visa_keeps_the_quote_that_justified_it_through_a_replay(
    store_conn: sqlite3.Connection,
    taxonomy: Taxonomy,
    geo_index: GeoIndex,
    profile: Profile,
    llm: FakeLlm,
) -> None:
    posting_id = _ingest(store_conn, taxonomy, geo_index, profile)
    review_all(store_conn, profile=profile, geo=geo_index, cfg=llm.config())

    replay.run_replay(store_conn, taxonomy=taxonomy, geo=geo_index, profile=profile, apply=True)

    row = store_conn.execute(
        "SELECT visa_evidence FROM postings WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    assert row["visa_evidence"] == "Work permit assistance will be provided for the right candidate"
