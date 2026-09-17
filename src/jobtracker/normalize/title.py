"""Title cleaning and role-family classification — blueprint/wp/WP03-normalize.md §3.

`clean_title` strips marketing noise for display; `title_raw` is kept
untouched next to it (cleanup is a hypothesis, not a fact). `classify_role`
decides the family from title **and** description — the discriminating case
is a bare "Software Engineer" at a prop shop: `swe_platform`, not `other`
(blueprint/10-PROFILE-TARGET.md §2).
"""

import re

from jobtracker.core.enums import RoleFamily
from jobtracker.normalize.taxonomy import Taxonomy

_REQ_CODE = re.compile(r"\b(?:REQ|JR|JOB|REF)[-_ ]?#?\d{3,}\b", re.IGNORECASE)
_GENDER_NOISE = re.compile(
    r"[\(\[]\s*[fhmw]\s*/\s*[fhmwx](?:\s*/\s*[dx])?\s*[\)\]]|\bH/F\b", re.IGNORECASE
)
_YEAR_NOISE = re.compile(
    r"[,\-–—]?\s*\(?\b(?:class of|start(?:ing)?|cohort|intake)\s*(?:19|20)\d{2}\b\)?"
    r"|\(?\b(?:19|20)\d{2}\s*(?:start|intake|cohort)\b\)?",
    re.IGNORECASE,
)
_LOCATION_SUFFIX = re.compile(r"\s*[—\-]\s*(?:remote|onsite|hybrid)\b.*$", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_EMPTY_PARENS = re.compile(r"\(\s*\)|\[\s*\]")


def clean_title(title_raw: str) -> str:
    """A display-ready title: requisition codes, gender markers and class-year noise removed."""
    text = _REQ_CODE.sub(" ", title_raw)
    text = _GENDER_NOISE.sub(" ", text)
    text = _YEAR_NOISE.sub("", text)
    text = _LOCATION_SUFFIX.sub("", text)
    text = _EMPTY_PARENS.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip(" -–—,")
    return text or title_raw.strip()


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    return any(needle in haystack for needle in needles)


def classify_role(title: str, description: str, *, taxonomy: Taxonomy) -> RoleFamily:
    """Decide the role family. Never raises (invariant I1) — worst case is `OTHER`.

    Title first, always: the description is boilerplate shared by every open
    role at a company (the same "we push cutting-edge research" paragraph
    appears under a Facilities Manager posting and an FPGA Engineer one), so
    scanning it for context keywords before the title has already given a
    clear answer produces false positives. Description is only consulted for
    a title that names no context at all — the case the primer itself
    expects to need it for.
    """
    rules = taxonomy.role_families
    title_l = f" {title.lower()} "
    description_l = f" {description.lower()} "

    # "Sales Trader" must resolve as trading, not fall into a generic "sales"
    # exclusion — check the specific trading title before the broad other one.
    if _contains_any(title_l, tuple(rules.quant_trading_keywords)):
        return RoleFamily.QUANT_TRADING
    if _contains_any(title_l, tuple(rules.other_keywords)):
        return RoleFamily.OTHER
    if _contains_any(title_l, tuple(rules.data_eng_keywords)):
        return RoleFamily.DATA_ENG
    if _contains_any(title_l, tuple(rules.risk_keywords)):
        return RoleFamily.RISK
    if _contains_any(title_l, tuple(rules.quant_dev_strong_keywords)):
        return RoleFamily.QUANT_DEV

    is_engineering = _contains_any(title_l, tuple(rules.engineering_head_words))
    is_research_titled = _contains_any(title_l, tuple(rules.research_head_words))
    has_quant_context = _contains_any(title_l, tuple(rules.quant_dev_context_keywords))
    has_infra_context = _contains_any(title_l, tuple(rules.swe_infra_context_keywords))

    # A title's head noun decides the track: "Engineer"/"Developer" wins over
    # a context word like "AI Research" appearing earlier in the same title
    # ("Campus AI Research Engineer" builds things; "AI Research Scientist"
    # studies them) — a context keyword alone never overrides a research
    # head noun into the engineering track. But an infra/quant word can still
    # pull in a title with *no* head noun at all ("Reliability Specialist").
    if is_engineering or ((has_quant_context or has_infra_context) and not is_research_titled):
        if has_quant_context:
            return RoleFamily.QUANT_DEV
        if has_infra_context:
            return RoleFamily.SWE_PLATFORM
        # Bare "Engineer"/"Developer": consult the description once, since
        # the title itself named no context — then default to swe_platform,
        # per the primer's own reading of a generic "Software Engineer".
        if _contains_any(description_l, tuple(rules.quant_dev_context_keywords)):
            return RoleFamily.QUANT_DEV
        return RoleFamily.SWE_PLATFORM

    if is_research_titled:
        if _contains_any(title_l, tuple(rules.data_eng_keywords)):
            return RoleFamily.DATA_ENG
        return RoleFamily.QUANT_RESEARCH

    if _contains_any(title_l, tuple(rules.quant_research_keywords)):
        return RoleFamily.QUANT_RESEARCH
    if " quant " in title_l:
        return RoleFamily.QUANT_RESEARCH

    return RoleFamily.OTHER
