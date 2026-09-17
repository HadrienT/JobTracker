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


# The dedup resolution order (blueprint/03-INTERFACES.md §3.4, blueprint/00-PRIMER.md
# §2 P2) hinges on this exact split: an ATS record is canonical because it carries
# the real apply URL; an aggregator is always demoted to an alias of it.
AGGREGATOR_SOURCES = frozenset({Source.EFC, Source.WTTJ, Source.LINKEDIN, Source.INDEED})


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
