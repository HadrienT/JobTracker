"""Enumerations shared across every package — see blueprint/03-INTERFACES.md §1.

All StrEnum: readable in SQLite, JSON and front URLs alike. Values are
persisted, compared in tests and embedded in shareable front URLs — add
freely, never rename without a migration.
"""

from enum import StrEnum


class Source(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    SMARTRECRUITERS = "smartrecruiters"
    WORKABLE = "workable"
    RECRUITEE = "recruitee"
    PERSONIO = "personio"
    WORKDAY = "workday"
    CUSTOM = "custom"
    EFC = "efinancialcareers"
    WTTJ = "wttj"
    LINKEDIN = "linkedin"
    INDEED = "indeed"
    ADZUNA = "adzuna"


# The dedup resolution order (blueprint/03-INTERFACES.md §3.4, blueprint/00-PRIMER.md
# §2 P2) hinges on this exact split: an ATS record is canonical because it carries
# the real apply URL; an aggregator is always demoted to an alias of it.
AGGREGATOR_SOURCES = frozenset(
    {Source.EFC, Source.WTTJ, Source.LINKEDIN, Source.INDEED, Source.ADZUNA}
)


class RoleFamily(StrEnum):
    QUANT_DEV = "quant_dev"
    QUANT_RESEARCH = "quant_research"
    QUANT_TRADING = "quant_trading"
    SWE_PLATFORM = "swe_platform"
    DATA_ENG = "data_eng"
    RISK = "risk"
    OTHER = "other"


class Seniority(StrEnum):
    INTERN = "intern"
    GRADUATE = "graduate"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    UNKNOWN = "unknown"


class VisaStatus(StrEnum):
    SPONSORS = "sponsors"
    NO = "no"
    UNKNOWN = "unknown"


class ApplicationStatus(StrEnum):
    """Where an application stands — the user's, set by hand. Absent means "not tracked"."""

    APPLIED = "applied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ApplicationOrigin(StrEnum):
    """How an application reached the table (blueprint/wp/WP21-applications.md §2)."""

    IMPORT = "import"  # the history: the user's spreadsheet and folder of screenshots
    FEED = "feed"  # a status set on a collected posting
    CLI = "cli"  # `jobtracker apply`, after a tailored CV


class Triage(StrEnum):
    """The user's verdict on a posting they do not want in the main feed any more.

    Absent means "not triaged yet". Both values take the posting out of the feed and
    into a list of its own, from which the verdict can be changed or cleared.
    """

    NO = "no"
    MAYBE = "maybe"


class ReviewOutcome(StrEnum):
    """What one LLM re-read of a posting concluded (blueprint/wp/WP19-llm-review.md)."""

    CORRECTED = "corrected"  # the reading changed at least one field
    CONFIRMED = "confirmed"  # read, and the stored values stand
    SET_ASIDE = "set_aside"  # under-confident or non-conforming: nothing was applied


class RemoteMode(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class SalaryPeriod(StrEnum):
    YEAR = "year"
    MONTH = "month"
    DAY = "day"
    HOUR = "hour"


class Tier(StrEnum):
    STRONG = "strong"
    POSSIBLE = "possible"
    STRETCH = "stretch"
    REJECTED = "rejected"


class Track(StrEnum):
    """A search scored against its own profile, beside the quant feed — blueprint/wp/WP20-tracks.md.

    The quant feed is not a track: it is the default, scored into `verdicts` and the
    `postings` row itself. A track adds `track_verdicts` rows for the postings in its scope.
    """

    CH_TECH = "ch_tech"
