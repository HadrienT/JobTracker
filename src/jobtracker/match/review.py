"""The whole-feed LLM re-read — blueprint/wp/WP19-llm-review.md. Pure: no socket, no database.

The rule that makes it safe to let a model *correct* fields, not just fill them: **nothing the
model says is believed until it has been found in the text.** Every value comes with a verbatim
quote; the quote must occur in the posting (title, location or description); the figure or the
city the model claims must occur in the quote. A hallucinated salary has no quote to hide behind,
and a real quote cannot carry a number it does not contain. What survives is then checked
against what the rules already found, and applied under a policy that is deliberately lopsided:
filling a gap needs `llm.min_confidence`, replacing a value the rules found needs
`review.override_confidence`, and nothing is ever *erased*.

`plan_review` is the whole decision, as a function of the model's reply. `runtime.review` owns
the socket and the database and merely carries the reply here and the plan back out.
"""

import calendar
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict

from jobtracker.core.enums import (
    RemoteMode,
    ReviewOutcome,
    SalaryPeriod,
    Seniority,
    VisaStatus,
)
from jobtracker.core.geo import GeoIndex, resolve_city
from jobtracker.core.models import Compensation, FieldCorrection, Location, Posting
from jobtracker.core.money import amounts_in, detect_period, is_weekly
from jobtracker.match.profile import Profile

REVIEW_SYSTEM_PROMPT = """\
You re-read one job posting for a quantitative-finance job feed and extract structured facts \
from it. Answer only with JSON matching the given schema.

Rules:
- Extract ONLY what the text itself states. Never infer, never use outside knowledge, never \
guess. A field the text does not state is null (or "unknown").
- Every value that is not null or "unknown" must come with its `evidence`: a short quote copied \
VERBATIM, character for character, from the posting (its title, its location field or its \
description). If you cannot quote it, leave the field null.
- compensation: the BASE pay this role offers. Amounts are plain digits in a string, no currency \
symbol and no separator ("175000"). Ignore bonuses, sign-on payments, equity, fund sizes, \
revenues and the pay of other roles. If the text gives different ranges for different \
locations, take the one for this posting's location; if that is unclear, leave it null. \
currency is the ISO 4217 code; period is what the amounts are per (year, month, day or hour).
- locations: every place the role can be done, one entry per city. country is the ISO 3166-1 \
alpha-2 code. remote_mode is onsite, hybrid or remote as the text says, else unknown. A plain \
"Remote" gives one entry with a null city and a null country.
- visa_sponsorship="no" ONLY if the text excludes sponsorship or requires a pre-existing right \
to work. If the text says nothing about visas, the answer is "unknown". It is not "no".
- min_years is the minimum REQUIRED, never the top of a stated range.
- "PhD preferred" is NOT phd_required. Neither is "PhD or equivalent experience".
- closes_at only if the text states an application deadline as a calendar date (YYYY-MM-DD).
- confidence is your confidence in the whole extraction, from 0 to 1.
"""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewCompensation(_Strict):
    amount_min: str | None
    amount_max: str | None
    currency: str | None
    period: SalaryPeriod | None
    evidence: str | None


class ReviewLocation(_Strict):
    city: str | None
    country: str | None
    remote_mode: RemoteMode
    evidence: str | None


class ReviewOutput(_Strict):
    """What the model must return. Every claim carries the quote that supports it."""

    compensation: ReviewCompensation
    locations: list[ReviewLocation]
    seniority: Seniority
    min_years: int | None
    seniority_evidence: str | None
    visa_sponsorship: VisaStatus
    visa_evidence: str | None
    phd_required: bool
    phd_evidence: str | None
    closes_at: str | None
    closes_evidence: str | None
    confidence: float


@dataclass(frozen=True)
class ReviewSources:
    """The text the model was shown — the only places a quote may come from."""

    title: str
    location: str | None
    description: str

    def haystack(self) -> str:
        return _squash(
            " ".join(part for part in (self.title, self.location, self.description) if part)
        )


def review_user_content(
    posting: Posting, sources: ReviewSources, *, max_description_chars: int
) -> str:
    return (
        f"Company: {posting.company_slug}\n"
        f"Title: {sources.title}\n"
        f"Location field: {sources.location or '(none)'}\n\n"
        f"Description:\n{sources.description[:max_description_chars]}"
    )


@dataclass(frozen=True)
class ReviewPlan:
    posting: Posting  # the posting with the accepted corrections applied (== input if none)
    corrections: tuple[FieldCorrection, ...]
    outcome: ReviewOutcome
    confidence: float | None
    # Fields the model claimed but that failed the checks, with why: the report's raw material,
    # and the way to tell "the model is wrong" from "the checks are too strict".
    refused: tuple[str, ...] = ()
    # Cities the model found that the referential does not know: the list of what to add to
    # configs/geo.yaml (with coordinates — never invented here).
    unknown_cities: tuple[tuple[str, str | None], ...] = field(default=())


def _squash(text: str) -> str:
    """Lowercase, punctuation and whitespace collapsed: "£120,000" and "120 000" compare equal."""
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


# The prompt labels its parts ("Location field: London"); a model quoting a line quotes the label
# with it. The label is ours, not the posting's: it is not held against the quote.
_PROMPT_LABEL_RE = re.compile(
    r"^\s*(?:title|location field|company|description)\s*:\s*", re.IGNORECASE
)


def _quoted(quote: str | None, haystack: str, *, minimum: int) -> bool:
    if quote is None:
        return False
    # Length is judged on what the model wrote; presence on what is left once our label is off.
    squashed = _squash(_PROMPT_LABEL_RE.sub("", quote))
    return len(_squash(quote)) >= minimum and squashed in haystack


def plan_review(
    posting: Posting,
    output: ReviewOutput | None,
    *,
    sources: ReviewSources,
    profile: Profile,
    geo: GeoIndex,
) -> ReviewPlan:
    """Decide what, if anything, of the model's reading is applied. Pure and deterministic."""
    if output is None or output.confidence < profile.llm.min_confidence:
        return ReviewPlan(
            posting=posting,
            corrections=(),
            outcome=ReviewOutcome.SET_ASIDE,
            confidence=None if output is None else output.confidence,
        )

    planner = _Planner(posting, output, sources, profile, geo)
    planner.compensation()
    planner.locations()
    planner.seniority()
    planner.visa()
    planner.phd()
    planner.closes_at()

    outcome = ReviewOutcome.CORRECTED if planner.corrections else ReviewOutcome.CONFIRMED
    updated = posting
    if planner.corrections:
        updates = dict(planner.updates)
        if _touches_classification(planner.corrections):
            updates["resolver_stage"] = "llm"  # the LLM settled a field the rules had settled
        updated = posting.model_copy(update=updates)
    return ReviewPlan(
        posting=updated,
        corrections=tuple(planner.corrections),
        outcome=outcome,
        confidence=output.confidence,
        refused=tuple(planner.refused),
        unknown_cities=tuple(planner.unknown_cities),
    )


# A quote has to say the thing, not merely sit near it. These are word cues, not numbers: "PhD
# degree in mathematics" says a qualification, "the PhD quant internship is a 10-week program"
# does not; "we encourage citizens to apply" is not "we cannot sponsor".
_PHD_RE = re.compile(r"ph\.?\s?d|doctorate|doctoral", re.IGNORECASE)
_REQUIREMENT_RE = re.compile(
    r"require|must|degree|qualif|holding|hold a|enrolled|pursuing|completing|candidate",
    re.IGNORECASE,
)
_VISA_NO_RE = re.compile(
    r"unable to|not able to|cannot|can't|can not|do not|does not|don't|no sponsorship"
    r"|without sponsorship|not offer|must (?:already )?(?:have|hold|be)|right to work"
    r"|eligible to work|authori[sz]ed to work|only (?:citizens|residents)",
    re.IGNORECASE,
)
_VISA_SPONSORS_RE = re.compile(r"sponsor|visa|work permit|relocat|immigration", re.IGNORECASE)
_MODE_CUES = {
    RemoteMode.REMOTE: re.compile(r"remote|work from home|wfh", re.IGNORECASE),
    RemoteMode.HYBRID: re.compile(r"hybrid", re.IGNORECASE),
    RemoteMode.ONSITE: re.compile(r"on-?site|in[- ]office|in[- ]person|on location", re.IGNORECASE),
}

# A level is only as good as the word that names it: "3+ years of experience" is a number of years
# (the rules turn years into a level), not the word "senior".
_LEVEL_WORDS = {
    Seniority.INTERN: re.compile(r"intern", re.IGNORECASE),
    Seniority.GRADUATE: re.compile(r"graduate|new grad|campus|early career", re.IGNORECASE),
    Seniority.JUNIOR: re.compile(r"junior|entry|\bjr\b", re.IGNORECASE),
    Seniority.MID: re.compile(r"mid[- ]level|intermediate|\bmid\b", re.IGNORECASE),
    Seniority.SENIOR: re.compile(r"senior|\bsr\b|experienced|principal|staff", re.IGNORECASE),
    Seniority.LEAD: re.compile(r"\blead\b|head of|principal|director|manager", re.IGNORECASE),
}

_CLASSIFICATION_FIELDS = frozenset({"seniority", "min_years", "visa_sponsorship", "phd_required"})


def _touches_classification(corrections: list[FieldCorrection]) -> bool:
    return any(c.field in _CLASSIFICATION_FIELDS for c in corrections)


class _Planner:
    """Accumulates accepted corrections field by field; each method is one field's whole policy."""

    def __init__(
        self,
        posting: Posting,
        output: ReviewOutput,
        sources: ReviewSources,
        profile: Profile,
        geo: GeoIndex,
    ) -> None:
        self.posting = posting
        self.out = output
        self.profile = profile
        self.geo = geo
        self.haystack = sources.haystack()
        self.minimum = profile.review.evidence_min_chars
        self.corrections: list[FieldCorrection] = []
        self.updates: dict[str, Any] = {}
        self.refused: list[str] = []
        self.unknown_cities: list[tuple[str, str | None]] = []

    # -- shared -----------------------------------------------------------------------------

    def _quoted(self, quote: str | None) -> bool:
        return _quoted(quote, self.haystack, minimum=self.minimum)

    def _verified(self, quote: str | None) -> str | None:
        """The quote itself when it is really in the posting, else None."""
        return quote if quote is not None and self._quoted(quote) else None

    def _refuse(self, field_name: str, why: str) -> None:
        self.refused.append(f"{field_name}: {why}")

    def _may_replace(self) -> bool:
        return self.out.confidence >= self.profile.review.override_confidence

    def _accept(
        self, field_name: str, before: Any, after: Any, evidence: str | None, **update: Any
    ) -> None:
        self.corrections.append(
            FieldCorrection(
                field=field_name,
                before=before,
                after=after,
                evidence=evidence,
                confidence=self.out.confidence,
            )
        )
        self.updates.update(update)

    # -- compensation -----------------------------------------------------------------------

    def compensation(self) -> None:
        comp = self.out.compensation
        if comp.amount_min is None and comp.amount_max is None:
            return
        evidence = self._verified(comp.evidence)
        if evidence is None:
            self._refuse("compensation", "its quote is not in the posting")
            return
        try:
            low = None if comp.amount_min is None else Decimal(comp.amount_min)
            high = None if comp.amount_max is None else Decimal(comp.amount_max)
        except InvalidOperation:
            self._refuse("compensation", "an amount is not a number")
            return
        quoted_amounts = amounts_in(evidence)
        for amount in (low, high):
            if amount is not None and amount not in quoted_amounts:
                self._refuse("compensation", f"{amount} is not a figure of its own quote")
                return
        if low is not None and high is not None and low > high:
            self._refuse("compensation", "the minimum exceeds the maximum")
            return
        currency = (comp.currency or "").upper()
        if currency not in self.profile.review.currencies:
            self._refuse("compensation", f"currency {comp.currency!r} is not a known one")
            return
        if comp.period is None:
            self._refuse("compensation", "no period")
            return
        if is_weekly(evidence):
            self._refuse("compensation", "a weekly figure: the feed stores no weekly period")
            return
        stated = detect_period(evidence)
        if stated is not None and stated is not comp.period:
            self._refuse("compensation", f"its quote says {stated.value}, not {comp.period.value}")
            return
        bounds = self.profile.review.salary_bounds.get(comp.period.value)
        if bounds is not None and any(
            amount is not None and not bounds[0] <= amount <= bounds[1] for amount in (low, high)
        ):
            self._refuse("compensation", "an amount is implausible for its period")
            return

        current = self.posting.compensation
        proposed = (low, high, currency, comp.period)
        existing = (current.amount_min, current.amount_max, current.currency, current.period)
        if _same_pay(proposed, existing):
            return
        replacing = current.amount_min is not None or current.amount_max is not None
        if replacing and not self._may_replace():
            self._refuse("compensation", "differs from the rules' figure at too low a confidence")
            return
        self._accept(
            "compensation",
            _comp_json(current),
            {
                "amount_min": None if low is None else str(low),
                "amount_max": None if high is None else str(high),
                "currency": currency,
                "period": comp.period.value,
            },
            evidence,
            compensation=Compensation(
                amount_min=low,
                amount_max=high,
                currency=currency,
                period=comp.period,
                bonus_mentioned=current.bonus_mentioned,
                equity_mentioned=current.equity_mentioned,
                raw=current.raw,
            ),
        )

    # -- locations --------------------------------------------------------------------------

    def locations(self) -> None:
        if len(self.out.locations) > self.profile.review.max_locations:
            self._refuse("locations", "more places than a location field holds")
            return
        proposed: list[Location] = []
        for entry in self.out.locations:
            location = self._location(entry)
            if location is not None:
                proposed.append(location)
        if not proposed:
            return

        existing = list(self.posting.locations)
        located = [loc for loc in existing if loc.city is not None]
        merged = _merge_locations(existing, located, proposed)
        if _location_key(merged) == _location_key(existing):
            return
        evidence = next((e.evidence for e in self.out.locations if e.evidence), None)
        self._accept(
            "locations",
            [_location_json(loc) for loc in existing],
            [_location_json(loc) for loc in merged],
            evidence,
            locations=tuple(merged),
        )

    def _location(self, entry: ReviewLocation) -> Location | None:
        country = entry.country.upper() if entry.country else None
        if country is not None and not re.fullmatch(r"[A-Z]{2}", country):
            self._refuse("locations", f"{entry.country!r} is not an ISO country code")
            return None
        if entry.city is None:
            # "Remote", or a country on its own: a mode/country fact, no pin.
            if country is None and entry.remote_mode is RemoteMode.UNKNOWN:
                return None
            if not self._quoted(entry.evidence):
                self._refuse("locations", "a location's quote is not in the posting")
                return None
            return Location(
                city=None,
                country=country,
                region=None,
                remote_mode=entry.remote_mode,
                raw=self.posting.locations[0].raw if self.posting.locations else None,
            )
        if not self._quoted(entry.evidence) or _squash(entry.city) not in _squash(
            entry.evidence or ""
        ):
            self._refuse("locations", f"the quote does not contain {entry.city!r}")
            return None
        resolved = resolve_city(self.geo, entry.city, hq_country=country)
        if resolved is None:
            self.unknown_cities.append((entry.city, country))
            return None
        if country is not None and resolved.country != country:
            self._refuse("locations", f"{entry.city!r} is not in {country}")
            return None
        return Location(
            city=resolved.city,
            country=resolved.country,
            region=resolved.region,
            remote_mode=self._mode(entry),
            raw=self.posting.locations[0].raw if self.posting.locations else None,
        )

    def _mode(self, entry: ReviewLocation) -> RemoteMode:
        """The mode the model claims, if — and only if — the quote itself says it.

        "Location field: New York" says a city, not "on-site": a mode inferred from a bare city
        name would stamp every posting `onsite`.
        """
        cue = _MODE_CUES.get(entry.remote_mode)
        if cue is None or not cue.search(entry.evidence or ""):
            return RemoteMode.UNKNOWN
        return entry.remote_mode

    # -- classification ---------------------------------------------------------------------

    def seniority(self) -> None:
        out = self.out
        current = self.posting
        seniority_changes = (
            out.seniority is not Seniority.UNKNOWN and out.seniority is not current.seniority
        )
        years_change = out.min_years is not None and out.min_years != current.min_years
        if not seniority_changes and not years_change:
            return  # the reading agrees with what is stored: nothing to prove, nothing to refuse
        evidence = self._verified(out.seniority_evidence)
        if evidence is None:
            self._refuse("seniority", "its quote is not in the posting")
            return
        level_word = _LEVEL_WORDS.get(out.seniority)
        if seniority_changes and level_word is not None and not level_word.search(evidence):
            self._refuse("seniority", f"its quote never names the level {out.seniority.value!r}")
        elif seniority_changes:
            fills = current.seniority is Seniority.UNKNOWN
            if fills or self._may_replace():
                self._accept(
                    "seniority",
                    current.seniority.value,
                    out.seniority.value,
                    evidence,
                    seniority=out.seniority,
                )
            else:
                self._refuse("seniority", "differs from the rules' value at too low a confidence")
        if out.min_years is not None and out.min_years != current.min_years:
            in_quote = Decimal(out.min_years) in amounts_in(evidence)
            if not in_quote:
                self._refuse("min_years", "the figure is not in its quote")
            elif current.min_years is None or self._may_replace():
                self._accept(
                    "min_years",
                    current.min_years,
                    out.min_years,
                    evidence,
                    min_years=out.min_years,
                )
            else:
                self._refuse("min_years", "differs from the rules' value at too low a confidence")

    def visa(self) -> None:
        out = self.out
        current = self.posting
        if (
            out.visa_sponsorship is VisaStatus.UNKNOWN
            or out.visa_sponsorship is current.visa_sponsorship
        ):
            return
        if not self._quoted(out.visa_evidence):
            self._refuse("visa_sponsorship", "its quote is not in the posting")
            return
        cue = _VISA_NO_RE if out.visa_sponsorship is VisaStatus.NO else _VISA_SPONSORS_RE
        if not cue.search(out.visa_evidence or ""):
            self._refuse("visa_sponsorship", "its quote does not state what the answer claims")
            return
        fills = current.visa_sponsorship is VisaStatus.UNKNOWN
        if not fills and not self._may_replace():
            self._refuse(
                "visa_sponsorship", "differs from the rules' value at too low a confidence"
            )
            return
        self._accept(
            "visa_sponsorship",
            current.visa_sponsorship.value,
            out.visa_sponsorship.value,
            out.visa_evidence,
            visa_sponsorship=out.visa_sponsorship,
            visa_evidence=out.visa_evidence,
        )

    def phd(self) -> None:
        # Only ever False -> True: "PhD required" is what the rules look for, and a model that
        # disagrees with a match is far more often wrong than the pattern.
        out = self.out
        if not out.phd_required or self.posting.phd_required:
            return
        if not self._quoted(out.phd_evidence) or not _PHD_RE.search(out.phd_evidence or ""):
            self._refuse("phd_required", "its quote does not mention a PhD")
            return
        if not _REQUIREMENT_RE.search(out.phd_evidence or ""):
            self._refuse("phd_required", "its quote mentions a PhD but states no requirement")
            return
        if not self._may_replace():
            self._refuse("phd_required", "asserted at too low a confidence")
            return
        self._accept("phd_required", False, True, out.phd_evidence, phd_required=True)

    def closes_at(self) -> None:
        out = self.out
        if out.closes_at is None or self.posting.closes_at is not None:
            return
        if not self._quoted(out.closes_evidence):
            self._refuse("closes_at", "its quote is not in the posting")
            return
        try:
            deadline = date.fromisoformat(out.closes_at)
        except ValueError:
            self._refuse("closes_at", "not a calendar date")
            return
        if deadline < self.posting.first_seen_at.date():
            self._refuse("closes_at", "the date is before the posting was first seen")
            return
        if not _date_in_quote(deadline, out.closes_evidence or ""):
            self._refuse("closes_at", "the date is not written in its quote")
            return
        moment = datetime(deadline.year, deadline.month, deadline.day, tzinfo=UTC)
        self._accept("closes_at", None, moment.isoformat(), out.closes_evidence, closes_at=moment)


def _same_pay(
    a: tuple[Decimal | None, Decimal | None, str, SalaryPeriod | None],
    b: tuple[Decimal | None, Decimal | None, str | None, SalaryPeriod | None],
) -> bool:
    """Equal, treating a single figure the same however it is spelt: 145k, 145k-145k.

    The rules store one figure as min == max; a reading may say it as "min only". Neither is a
    correction of the other.
    """
    low_a, high_a, currency_a, period_a = a
    low_b, high_b, currency_b, period_b = b
    if (currency_a, period_a) != (currency_b, period_b):
        return False
    if (low_a, high_a) == (low_b, high_b):
        return True
    single_a = {x for x in (low_a, high_a) if x is not None}
    single_b = {x for x in (low_b, high_b) if x is not None}
    one_figure = len(single_a) == 1 and len(single_b) == 1
    return one_figure and single_a == single_b and (low_a == high_a or low_b == high_b)


def _date_in_quote(deadline: date, quote: str) -> bool:
    """The year and the day appear as numbers, the month as a number or a name: "12/23/2026",
    "23 December 2026" and "December 23, 2026" all carry 2026-12-23; a date the model computed
    from "in three weeks" carries nothing."""
    numbers = {int(n) for n in re.findall(r"\d+", quote)}
    lowered = quote.lower()
    month_named = (
        calendar.month_name[deadline.month].lower() in lowered
        or calendar.month_abbr[deadline.month].lower() in lowered
    )
    return (
        deadline.year in numbers
        and deadline.day in numbers
        and (deadline.month in numbers or month_named)
    )


def _comp_json(comp: Compensation) -> dict[str, str | None]:
    return {
        "amount_min": None if comp.amount_min is None else str(comp.amount_min),
        "amount_max": None if comp.amount_max is None else str(comp.amount_max),
        "currency": comp.currency,
        "period": comp.period.value if comp.period else None,
    }


def _same_place(a: Location, b: Location) -> bool:
    return (a.city, a.country, a.remote_mode) == (b.city, b.country, b.remote_mode)


def _location_json(loc: Location) -> dict[str, str | None]:
    return {"city": loc.city, "country": loc.country, "remote_mode": loc.remote_mode.value}


def _location_key(locations: list[Location]) -> set[tuple[str | None, str | None, str]]:
    return {(loc.city, loc.country, loc.remote_mode.value) for loc in locations}


def _merge_locations(
    existing: list[Location], located: list[Location], proposed: list[Location]
) -> list[Location]:
    """The lopsided merge: fill what is missing, never drop what is there.

    No located city yet -> the model's cities take their place (the citiless entries — a bare
    "Remote", a country — stay, unless the model restates them). Otherwise -> only the cities
    the posting lacks are added, and a city whose mode the rules could not read gets the
    model's reading.
    """
    if not located:
        new_cities = [loc for loc in proposed if loc.city is not None]
        restated = [loc for loc in proposed if loc.city is None]
        # An existing citiless entry stays only if it says something (a country, a region, a
        # mode); the empty placeholder the rules leave for a string they could not read does not.
        kept = [
            loc
            for loc in existing
            if loc.city is None
            and (loc.country or loc.region or loc.remote_mode is not RemoteMode.UNKNOWN)
            and not any(_same_place(loc, r) for r in restated)
        ]
        return new_cities + kept + restated
    by_city = {(loc.city, loc.country): loc for loc in existing if loc.city is not None}
    merged = list(existing)
    for loc in proposed:
        if loc.city is None:
            continue
        key = (loc.city, loc.country)
        if key not in by_city:
            merged.append(loc)
        elif (
            by_city[key].remote_mode is RemoteMode.UNKNOWN
            and loc.remote_mode is not RemoteMode.UNKNOWN
        ):
            merged = [loc if (m.city, m.country) == key else m for m in merged]
    return merged


__all__ = [
    "REVIEW_SYSTEM_PROMPT",
    "ReviewOutput",
    "ReviewPlan",
    "ReviewSources",
    "plan_review",
    "review_user_content",
]
