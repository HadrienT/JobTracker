"""Replay the normalizer on archived inputs and measure the delta — WP16 §2.

The reason this exists is the **regression line**: an improvement to the seniority
parser that quietly costs 0.7 points of location resolution is a trade-off to see
before committing, not three weeks later. So the report always says, per stage,
what resolved before, what resolves now, and shouts when a stage went down.

Rules that make it safe to run (blueprint/wp/WP16-feedback.md §2):
- a dry run by default — nothing is written without `apply=True`;
- it never collects: it reads `store.replay_inputs` only;
- `posting_id`, `fingerprint`, `first_seen_at` and every `user_flags` row survive;
- an LLM-resolved posting keeps the fields the LLM settled (the rules would only
  undo them).

Tier deltas compare `evaluate(before)` with `evaluate(after)` at the *same* moment,
so a posting getting older between two runs is never mistaken for a parser change.
"""

import sqlite3
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from jobtracker.core.enums import RoleFamily, Seniority, Source, VisaStatus
from jobtracker.core.errors import JobTrackerError
from jobtracker.core.geo import GeoIndex
from jobtracker.core.models import Posting, RawPosting
from jobtracker.match.profile import Profile
from jobtracker.match.score import evaluate
from jobtracker.normalize.cascade import NORMALIZE_VERSION, normalize
from jobtracker.normalize.taxonomy import Taxonomy
from jobtracker.store.postings import get_posting, update_resolution
from jobtracker.store.replay_inputs import ReplayInput, list_replay_inputs

_COMMIT_EVERY = 200


class UnknownStage(JobTrackerError):
    """`--stage` named something that is not a normalizer stage."""


@dataclass(frozen=True)
class Stage:
    fields: tuple[str, ...]
    resolved: Callable[[Posting], bool]


STAGES: dict[str, Stage] = {
    "seniority": Stage(("seniority", "min_years"), lambda p: p.seniority != Seniority.UNKNOWN),
    "visa": Stage(
        ("visa_sponsorship", "visa_evidence"), lambda p: p.visa_sponsorship != VisaStatus.UNKNOWN
    ),
    "location": Stage(("locations",), lambda p: any(loc.country for loc in p.locations)),
    "role": Stage(("role_family",), lambda p: p.role_family != RoleFamily.OTHER),
    "tech": Stage(("tech",), lambda p: bool(p.tech)),
    "compensation": Stage(("compensation",), lambda p: p.compensation.amount_min is not None),
}
# Recomputed on a full replay only: they have no "resolved" notion to measure.
_UNMEASURED_FIELDS = ("title", "phd_required", "languages_required", "posted_at")
# What an LLM resolution settled — never overwritten by the rules.
_LLM_OWNED = frozenset(
    {"role_family", "seniority", "min_years", "visa_sponsorship", "phd_required"}
)


@dataclass(frozen=True)
class StageRate:
    stage: str
    before: float
    after: float

    @property
    def delta_pts(self) -> float:
        return (self.after - self.before) * 100

    @property
    def regressed(self) -> bool:
        return self.after < self.before


@dataclass
class ReplayReport:
    total: int = 0
    versions_before: dict[int, int] = field(default_factory=dict)
    version_after: int = NORMALIZE_VERSION
    stages: list[StageRate] = field(default_factory=list)
    changed_postings: int = 0
    tier_net: dict[str, int] = field(default_factory=dict)
    tier_transitions: Counter[tuple[str, str]] = field(default_factory=Counter)
    applied: bool = False
    refused: str | None = None

    @property
    def regressions(self) -> list[StageRate]:
        return [s for s in self.stages if s.regressed]


def _raw_from(item: ReplayInput) -> RawPosting:
    return RawPosting(
        source=Source(item.source),
        company_slug=item.company_slug,
        source_job_id=item.source_job_id,
        url=item.url,
        title_raw=item.title_raw,
        description_raw=item.description,
        location_raw=item.location_raw,
        department_raw=None,
        posted_at_raw=item.posted_at_raw,
        payload=b"",
        fetched_at=datetime.fromisoformat(item.first_seen_at).astimezone(UTC),
        content_hash=item.content_hash,
    )


def _merge(old: Posting, new: Posting, *, stage: str | None) -> Posting:
    """The old posting with the replayed fields swapped in — identity fields never move."""
    if stage is None:
        names = [f for s in STAGES.values() for f in s.fields] + list(_UNMEASURED_FIELDS)
    else:
        names = list(STAGES[stage].fields)
    if old.resolver_stage == "llm":
        names = [n for n in names if n not in _LLM_OWNED]
    update: dict[str, Any] = {n: getattr(new, n) for n in names}
    if stage is None:
        update["normalize_version"] = new.normalize_version
    return old.model_copy(update=update)


def _comparable(posting: Posting) -> dict[str, Any]:
    """What the database can actually hold of `posting`: the rest would always look "changed".

    `get_posting` rebuilds `languages_required` and the compensation's bonus / equity / raw text
    as empty defaults (they are not persisted), while a replay recomputes them — comparing the
    two reports a change on nearly every posting that no `--apply` could ever write.
    """
    data = posting.model_dump(exclude={"normalize_version", "languages_required"})
    compensation = posting.compensation
    data["compensation"] = (
        compensation.amount_min,
        compensation.amount_max,
        compensation.currency,
        compensation.period,
    )
    return data


def _rate(postings: list[Posting], stage: Stage) -> float:
    return sum(1 for p in postings if stage.resolved(p)) / len(postings) if postings else 0.0


def run_replay(
    conn: sqlite3.Connection,
    *,
    taxonomy: Taxonomy,
    geo: GeoIndex,
    profile: Profile,
    stage: str | None = None,
    since: datetime | None = None,
    normalize_version_below: int | None = None,
    apply: bool = False,
    allow_regression: bool = False,
) -> ReplayReport:
    if stage is not None and stage not in STAGES:
        raise UnknownStage(f"unknown stage {stage!r}; expected one of {sorted(STAGES)}")

    inputs = list_replay_inputs(conn, since=since, normalize_version_below=normalize_version_below)
    report = ReplayReport(total=0)
    olds: list[Posting] = []
    merged: list[Posting] = []
    for item in inputs:
        old = get_posting(conn, item.posting_id)
        if old is None:
            continue
        new = normalize(_raw_from(item), taxonomy=taxonomy, geo=geo, hq_country=item.hq_country)
        olds.append(old)
        merged.append(_merge(old, new, stage=stage))
        report.versions_before[item.normalize_version] = (
            report.versions_before.get(item.normalize_version, 0) + 1
        )
    report.total = len(olds)

    measured = STAGES if stage is None else {stage: STAGES[stage]}
    report.stages = [
        StageRate(name, _rate(olds, spec), _rate(merged, spec)) for name, spec in measured.items()
    ]

    net: Counter[str] = Counter()
    for old, new in zip(olds, merged, strict=True):
        if _comparable(new) != _comparable(old):
            report.changed_postings += 1
        tier_before = evaluate(old, profile=profile).tier.value
        tier_after = evaluate(new, profile=profile).tier.value
        if tier_before != tier_after:
            net[tier_after] += 1
            net[tier_before] -= 1
            report.tier_transitions[(tier_before, tier_after)] += 1
    report.tier_net = {tier: n for tier, n in net.items() if n != 0}

    if not apply:
        return report
    if report.regressions and not allow_regression:
        names = ", ".join(s.stage for s in report.regressions)
        report.refused = f"refusing to apply: resolution regressed on {names} (--allow-regression)"
        return report

    for i, new in enumerate(merged, start=1):
        update_resolution(conn, new, evaluate(new, profile=profile))
        if i % _COMMIT_EVERY == 0:
            conn.commit()
    conn.commit()
    report.applied = True
    return report


def format_report(report: ReplayReport) -> str:
    if report.total == 0:
        return "nothing to replay: no archived posting matches the filters"
    before = ", ".join(f"v{v}: {n}" for v, n in sorted(report.versions_before.items()))
    lines = [
        f"replay over {report.total} archived postings, normalize_version [{before}] → "
        f"{report.version_after}",
        "",
        f"{'stage':<14}{'before':>9}{'after':>9}{'delta':>11}",
    ]
    for rate in report.stages:
        flag = "   ⚠ REGRESSION" if rate.regressed else ""
        lines.append(
            f"{rate.stage:<14}{rate.before * 100:>8.1f}%{rate.after * 100:>8.1f}%"
            f"{rate.delta_pts:>+9.1f} pts{flag}"
        )
    lines.append("")
    lines.append(f"postings whose fields change: {report.changed_postings}")
    if report.tier_net:
        parts = ", ".join(
            f"{n:+d} {tier}" for tier, n in sorted(report.tier_net.items(), key=lambda kv: -kv[1])
        )
        lost_strong = report.tier_net.get("strong", 0) < 0
        lines.append(
            f"tier changes: {parts}" + ("   ⚠ inspect the strong ones" if lost_strong else "")
        )
    else:
        lines.append("tier changes: none")
    if report.refused:
        lines += ["", report.refused]
    elif report.applied:
        lines += ["", "applied."]
    else:
        lines += ["", "dry run — nothing written (use --apply)."]
    return "\n".join(lines)
