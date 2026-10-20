"""Which titles are worth one more request — a request-budget filter, never a verdict.

A board that lists a title but keeps the description one request away (Workday, a
company's own portal) would cost a request per posting; a bank lists thousands of
roles no profile here will ever want. Collectors ask this before paying for a
description. A miss never drops a posting — it is stored with its title and an empty
description — so the list errs on the generous side: a false positive costs one
request, a false negative costs a posting scored on its title alone.

Role classification stays `normalize`'s job (blueprint/wp/WP06-collect-ats2.md §2).
"""

from __future__ import annotations

import re

# Substrings, in the languages the registry's boards post in (English, French, German).
_MARKERS = (
    "engineer",
    "ingénieur",
    "ingenieur",
    "develop",  # developer, development, développeur
    "dévelop",
    "entwickl",
    "programmer",
    "programmier",
    "software",
    "logiciel",
    "technolog",
    "quant",
    "scientist",
    "research",
    "recherche",
    "machine learning",
    "data",
    "analytics",
    "model",  # modelling, model validation
    "modél",
    "pricing",
    "valuation",
    "derivativ",
    "dérivé",
    "xva",
    "exotic",
    "volatil",
    "trading",
    "trader",
    "algo",
    "python",
    "c++",
    "java",
    # The ways in for a graduate: a bank files its junior quant roles under these.
    "graduate",
    "trainee",
    "intern",
    "stagiaire",
    "praktik",
    "werkstudent",
    "off cycle",
    "off-cycle",
    "alternan",
    "apprenti",
)
# Short tokens that only mean something as a whole word.
_WORDS = re.compile(r"\b(?:strats?|strategist|stage|v\.i\.e\.?|it|ai|ml|hpc|gpu)\b")
# The French international graduate contract, as an acronym: "assurance vie" is not one.
_VIE = re.compile(r"\bVIE\b")


def looks_relevant(title: str) -> bool:
    lowered = title.lower()
    return (
        any(marker in lowered for marker in _MARKERS)
        or _WORDS.search(lowered) is not None
        or _VIE.search(title) is not None
    )


__all__ = ["looks_relevant"]
