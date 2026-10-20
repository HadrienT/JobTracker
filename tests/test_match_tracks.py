"""Tracks in `match` — blueprint/wp/WP20-tracks.md §2-3.

Built from the real configs/profile.yaml + configs/tracks.yaml: the overlay rules and the
ch_tech track's own choices are what is under test, not a copy of them.
"""

from pathlib import Path
from typing import Any

import pytest

from factories_store import make_posting
from jobtracker.core.config import load_yaml
from jobtracker.core.enums import RemoteMode, RoleFamily, Seniority, Tier, Track
from jobtracker.core.errors import ConfigError
from jobtracker.core.models import Location
from jobtracker.match.profile import Profile, build_profile, build_tracks
from jobtracker.match.rules import hard_reject, in_scope, on_topic
from jobtracker.match.score import evaluate

pytestmark = [pytest.mark.contract, pytest.mark.usefixtures("frozen_clock")]

CONFIGS = Path(__file__).resolve().parent.parent / "configs"


def _zurich() -> tuple[Location, ...]:
    return (
        Location(
            city="Zurich", country="CH", region=None, remote_mode=RemoteMode.ONSITE, raw="Zurich"
        ),
    )


@pytest.fixture(scope="module")
def base() -> dict[str, Any]:
    return load_yaml(CONFIGS / "profile.yaml")


@pytest.fixture(scope="module")
def ch_tech(base: dict[str, Any]) -> Profile:
    tracks = build_tracks(
        base,
        load_yaml(CONFIGS / "tracks.yaml"),
        company_tiers={"nvidia": 1},
        company_sectors={"nvidia": "tech", "acme": "vendor"},
    )
    return tracks[Track.CH_TECH]


@pytest.fixture(scope="module")
def quant(base: dict[str, Any]) -> Profile:
    return build_profile(base, company_sectors={"nvidia": "tech", "acme": "vendor"})


# --- the overlay ----------------------------------------------------------------------------


def test_a_track_inherits_what_it_does_not_restate(ch_tech: Profile, quant: Profile) -> None:
    assert ch_tech.llm == quant.llm
    assert ch_tech.review == quant.review
    assert ch_tech.hard_rejects == quant.hard_rejects
    assert ch_tech.seniority == quant.seniority  # junior, like the quant profile
    assert ch_tech.titles.excluded == quant.titles.excluded


def test_a_track_overrides_what_it_restates(ch_tech: Profile, quant: Profile) -> None:
    assert ch_tech.scope.countries == frozenset({"CH"})
    assert ch_tech.scope.exclude_sectors == frozenset()
    assert ch_tech.weights["tech_cpp"] != quant.weights["tech_cpp"]
    # a weight it does not restate is the quant one: mappings merge key by key
    assert ch_tech.weights["seniority_match"] == quant.weights["seniority_match"]
    assert "cuda" in ch_tech.titles.strong
    assert ch_tech.topic is not None and quant.topic is None


def test_an_unknown_track_is_a_config_error(base: dict[str, Any]) -> None:
    with pytest.raises(ConfigError, match="unknown track"):
        build_tracks(base, {"tracks": {"mars_tech": {"version": 1}}})


def test_a_track_without_its_own_version_is_a_config_error(base: dict[str, Any]) -> None:
    with pytest.raises(ConfigError, match="version"):
        build_tracks(base, {"tracks": {"ch_tech": {"scope": {"countries": ["CH"]}}}})


def test_a_topic_naming_nothing_is_a_config_error(base: dict[str, Any]) -> None:
    with pytest.raises(ConfigError, match="topic"):
        build_tracks(base, {"tracks": {"ch_tech": {"version": 1, "topic": {"titles": []}}}})


def test_quant_niche_tags_are_unchanged_by_moving_them_to_config(quant: Profile) -> None:
    assert quant.niche_tech == frozenset({"kdb", "ocaml", "rust", "cuda", "fpga"})


# --- scope and topic ------------------------------------------------------------------------


def test_scope_is_a_swiss_location_among_several(ch_tech: Profile) -> None:
    paris = make_posting()
    both = make_posting(locations=(*paris.locations, *_zurich()))
    assert not in_scope(paris, profile=ch_tech)
    assert in_scope(both, profile=ch_tech)


def test_the_quant_feed_has_no_location_scope(quant: Profile) -> None:
    assert in_scope(make_posting(), profile=quant)


@pytest.mark.parametrize(
    ("title", "tech"),
    [
        ("C++ Software Engineer", frozenset()),
        ("Senior CUDA Developer", frozenset()),
        ("Machine Learning Engineer", frozenset()),
        ("ML Engineer, Perception", frozenset()),
        ("Software Engineer", frozenset({"cpp"})),
        ("Research Engineer", frozenset({"pytorch"})),
    ],
)
def test_on_topic_by_title_or_by_stack(ch_tech: Profile, title: str, tech: frozenset[str]) -> None:
    assert on_topic(make_posting(title=title, tech=tech), profile=ch_tech)


@pytest.mark.parametrize("title", ["Java Backend Developer", "HTML Integrator", "Product Owner"])
def test_off_topic_without_title_keyword_or_stack_tag(ch_tech: Profile, title: str) -> None:
    posting = make_posting(title=title, tech=frozenset({"java"}), locations=_zurich())
    assert not on_topic(posting, profile=ch_tech)
    assert hard_reject(posting, profile=ch_tech) == "off_topic"


def test_role_family_other_is_off_topic_on_a_track_not_quant(
    ch_tech: Profile, quant: Profile
) -> None:
    posting = make_posting(role_family=RoleFamily.OTHER, title="C++ Engineer")
    assert hard_reject(posting, profile=ch_tech) == "off_topic"
    assert hard_reject(posting, profile=quant) == "not_quant"


def test_the_quant_feed_rejects_a_tech_employer_whatever_the_title(quant: Profile) -> None:
    """Off topic, not `not_quant`: the LLM lane re-reads `not_quant`, never this."""
    posting = make_posting(company_slug="nvidia", title="Quant Developer")
    assert hard_reject(posting, profile=quant) == "off_topic"
    assert hard_reject(make_posting(company_slug="acme"), profile=quant) is None


def test_a_track_takes_a_tech_employer(ch_tech: Profile) -> None:
    posting = make_posting(company_slug="nvidia", title="CUDA Engineer", locations=_zurich())
    assert hard_reject(posting, profile=ch_tech) is None


def test_a_track_keeps_the_junior_rule(ch_tech: Profile) -> None:
    posting = make_posting(title="Staff C++ Engineer", locations=_zurich())
    assert hard_reject(posting, profile=ch_tech) == "senior_only"


# --- scoring --------------------------------------------------------------------------------


def test_a_junior_swiss_cuda_role_at_a_rank1_employer_is_strong(ch_tech: Profile) -> None:
    posting = make_posting(
        company_slug="nvidia",
        title="CUDA Software Engineer",
        seniority=Seniority.JUNIOR,
        tech=frozenset({"cpp", "cuda", "python"}),
        locations=_zurich(),
    )
    verdict = evaluate(posting, profile=ch_tech)
    assert verdict.tier == Tier.STRONG
    assert {r.code for r in verdict.reasons} >= {"title_strong", "tech_cpp", "tech_niche"}
    assert verdict.profile_version == ch_tech.version


def test_the_track_niche_is_the_ml_stack_not_kdb(ch_tech: Profile) -> None:
    kdb = make_posting(title="C++ Engineer", tech=frozenset({"kdb"}), locations=_zurich())
    torch = make_posting(title="C++ Engineer", tech=frozenset({"pytorch"}), locations=_zurich())
    assert "tech_niche" not in {r.code for r in evaluate(kdb, profile=ch_tech).reasons}
    assert "tech_niche" in {r.code for r in evaluate(torch, profile=ch_tech).reasons}


def test_a_cpp_title_keyword_matches_on_the_track_and_in_the_quant_profile(
    ch_tech: Profile, quant: Profile
) -> None:
    """ "c++" ends on a non-word character: a `\\b` boundary there never matched, silently."""
    posting = make_posting(title="C++ Developer", locations=_zurich())
    assert "title_strong" in {r.code for r in evaluate(posting, profile=ch_tech).reasons}
    assert "title_possible" in {r.code for r in evaluate(posting, profile=quant).reasons}


@pytest.mark.parametrize(
    "title", ["Internship - AI Software Engineer - CRM", "Quantitative Research Intern - AI"]
)
def test_ai_in_a_title_is_on_topic(ch_tech: Profile, title: str) -> None:
    assert on_topic(make_posting(title=title, tech=frozenset()), profile=ch_tech)


def test_ai_inside_a_word_is_not(ch_tech: Profile) -> None:
    assert not on_topic(
        make_posting(title="Email Campaign Manager", tech=frozenset()), profile=ch_tech
    )
