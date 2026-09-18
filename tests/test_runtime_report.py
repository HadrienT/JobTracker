"""The weekly report and the favorites → profile loop — WP16 §3, §4, §6."""

import hashlib
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from factories_store import make_board, make_posting, make_verdict
from jobtracker.collect.http import load_sources_config
from jobtracker.core.enums import Source, Tier
from jobtracker.match.profile import Profile, build_profile
from jobtracker.runtime.report import build_weekly_report, profile_suggestions
from jobtracker.store import llm_queue, reporting
from jobtracker.store.companies import ensure_discovered_company, sync_companies
from jobtracker.store.postings import mark_favorite, upsert_posting
from test_runtime_pipeline import _PROFILE_DATA

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parent.parent
_NOW = datetime(2026, 9, 18, tzinfo=UTC)


@pytest.fixture
def profile() -> Profile:
    return build_profile(_PROFILE_DATA)


def _store(
    conn: sqlite3.Connection,
    pid: str,
    *,
    score: int,
    tier: Tier,
    reason: str | None,
    slug: str = "acme",
    days_ago: int = 2,
    **overrides: object,
) -> None:
    seen = _NOW - timedelta(days=days_ago)
    posting = make_posting(
        posting_id=pid, source_job_id=pid, company_slug=slug, first_seen_at=seen,
        last_seen_at=seen, posted_at=seen, **overrides,
    )  # fmt: skip
    posting = posting.model_copy(update={"fingerprint": f"fp-{pid}"})
    upsert_posting(
        conn, posting, make_verdict(posting_id=pid, score=score, tier=tier, rejection_reason=reason)
    )


@pytest.fixture
def demo_db(store_conn: sqlite3.Connection) -> sqlite3.Connection:
    sync_companies(
        store_conn,
        [
            make_board(company_slug="acme", company_name="Acme"),
            make_board(company_slug="quiet_co", company_name="Quiet Co"),
        ],
    )
    _store(store_conn, "strong-1", score=88, tier=Tier.STRONG, reason=None)
    _store(store_conn, "possible-1", score=55, tier=Tier.POSSIBLE, reason=None)
    _store(store_conn, "rej-1", score=0, tier=Tier.REJECTED, reason="not_quant")
    _store(store_conn, "rej-2", score=0, tier=Tier.REJECTED, reason="senior_only")
    ensure_discovered_company(
        store_conn, slug="oxford_knight", name="Oxford Knight", source=Source.EFC, hq_country="GB"
    )
    # quiet_co: its only posting was last seen 40 days ago — a likely broken token.
    _store(store_conn, "stale-1", score=50, tier=Tier.POSSIBLE, reason=None, slug="quiet_co",
           days_ago=40)  # fmt: skip
    store_conn.execute("UPDATE postings SET resolver_stage = 'llm' WHERE posting_id = 'strong-1'")
    llm_queue.enqueue(store_conn, "possible-1", urgent=False, now=_NOW)
    llm_queue.record_skipped_attempt(store_conn, "possible-1", now=_NOW)
    store_conn.commit()
    return store_conn


def _report(conn: sqlite3.Connection, profile: Profile) -> str:
    config = load_sources_config(REPO_ROOT / "configs" / "sources.yaml")
    return build_weekly_report(conn, config, profile, now=_NOW)


def test_every_section_is_present_and_filled(demo_db: sqlite3.Connection, profile: Profile) -> None:
    text = _report(demo_db, profile)
    for heading in (
        "## 1. Couverture",
        "## 2. Santé des sources",
        "## 3. Sociétés à zéro offre depuis 30 jours",
        "## 4. Résolution du normaliseur",
        "## 5. Distribution des paliers",
        "## 6. Motifs de rejet",
        "## 7. Charge LLM",
        "## 8. Employeurs inconnus",
        "## 9. Favoris → profil",
    ):
        assert heading in text, heading
    assert "not_quant" in text and "senior_only" in text  # rejection reasons
    assert "offres tranchées par le LLM : 1" in text
    assert "tours sautés (serveur occupé ou éteint) : 1" in text
    assert "Oxford Knight" in text  # the unknown-employer section


def test_a_company_at_zero_postings_for_thirty_days_is_named(
    demo_db: sqlite3.Connection, profile: Profile
) -> None:
    assert reporting.silent_companies(demo_db, now=_NOW) == ["quiet_co"]
    section = _report(demo_db, profile).split("## 3.")[1].split("## 4.")[0]
    assert "`quiet_co`" in section and "`acme`" not in section


def test_favorites_on_rejected_postings_are_flagged_with_their_rejection_reason(
    demo_db: sqlite3.Connection, profile: Profile
) -> None:
    mark_favorite(demo_db, "rej-1", True)
    demo_db.commit()
    text = _report(demo_db, profile)
    assert "1 favori(s) sur des offres `stretch`/`rejected`" in text
    assert "not_quant" in text.split("## 9.")[1]


def test_the_report_proposes_and_never_touches_the_profile(
    demo_db: sqlite3.Connection, profile: Profile
) -> None:
    profile_file = REPO_ROOT / "configs" / "profile.yaml"
    digest = hashlib.sha256(profile_file.read_bytes()).hexdigest()
    mark_favorite(demo_db, "rej-1", True)
    demo_db.commit()
    text = _report(demo_db, profile)
    assert "reste écrit à la main" in text
    assert hashlib.sha256(profile_file.read_bytes()).hexdigest() == digest


def test_no_favorites_is_stated_not_guessed(demo_db: sqlite3.Connection, profile: Profile) -> None:
    assert "Aucun favori" in _report(demo_db, profile)


def test_over_represented_companies_and_a_low_median_are_suggested(profile: Profile) -> None:
    favs = [reporting.FavoriteRow(f"f{i}", "t", "hot_co", 30, "stretch", None) for i in range(4)]
    lifts = [reporting.Lift("hot_co", 4, 1.0, 0.2)]
    suggestions = profile_suggestions(favs, lifts, [], profile=profile)
    assert any("Score médian des favoris" in s for s in suggestions)
    assert any("`hot_co`" in s and "×5.0" in s for s in suggestions)


def test_a_thin_signal_is_not_over_interpreted(profile: Profile) -> None:
    favs = [reporting.FavoriteRow("f1", "t", "hot_co", 80, "strong", None)]
    lifts = [reporting.Lift("hot_co", 1, 1.0, 0.1)]  # one favorite: lift 10×, but only one
    assert profile_suggestions(favs, lifts, [], profile=profile) == [
        "Les favoris sont cohérents avec le profil : rien à ajuster."
    ]
