"""The project's rules, as executable checks — blueprint/wp/WP14-quality.md §2.1.

These test the *rules*, not the behavior. They are inelegant and very profitable: each
encodes an "interdit" of blueprint/00-PRIMER.md §5 in a form a machine can verify,
instead of a review that has to remember it. Where an AST is more reliable than a
`grep` (a comment that *mentions* `float(` is not a use of it), an AST is used.
"""

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from jobtracker.core.config import Settings
from jobtracker.core.enums import Source

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "jobtracker"


def _py_files(*parts: str) -> list[Path]:
    root = SRC.joinpath(*parts)
    return sorted(root.rglob("*.py")) if root.is_dir() else [root]


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT))


def _calls(tree: ast.AST) -> Iterator[ast.Call]:
    return (n for n in ast.walk(tree) if isinstance(n, ast.Call))


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return node.id if isinstance(node, ast.Name) else ""


# --- N6 / interdit n°11: no wall clock outside core/clock.py -----------------------------


def test_no_wall_clock_outside_core_clock() -> None:
    """`core.clock.utc_now()` only, so tests can freeze time (rule N6)."""
    forbidden = {"datetime.now", "datetime.utcnow", "datetime.datetime.now", "date.today"}
    hits = []
    for path in _py_files():
        if path.name == "clock.py" and path.parent.name == "core":
            continue
        for call in _calls(_tree(path)):
            if _dotted(call.func) in forbidden:
                hits.append(f"{_rel(path)}:{call.lineno} {_dotted(call.func)}()")
    assert not hits, "use core.clock.utc_now(): " + "; ".join(hits)


# --- N2 / interdit n°11: no float on money ---------------------------------------------------


_MONEY_FILES = ("core/money.py", "normalize/compensation.py")


def test_no_float_in_the_monetary_paths() -> None:
    hits = []
    for rel in _MONEY_FILES:
        path = SRC / rel
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and _dotted(node.func) == "float":
                hits.append(f"{rel}:{node.lineno} float()")
            if isinstance(node, ast.Name) and node.id == "float":
                hits.append(f"{rel}:{node.lineno} float annotation")
            if isinstance(node, ast.Constant) and isinstance(node.value, float):
                hits.append(f"{rel}:{node.lineno} float literal {node.value}")
    assert not hits, "money is Decimal (rule N2): " + "; ".join(hits)


def test_persisted_amounts_are_decimal_strings_never_sqlite_reals() -> None:
    schema = (REPO_ROOT / "migrations" / "0001_initial.sql").read_text(encoding="utf-8")
    for column in ("salary_min", "salary_max"):
        assert re.search(rf"{column} TEXT", schema), f"{column} must be TEXT, not REAL"


# --- ADR-007: keyset pagination, never OFFSET ------------------------------------------------


def test_no_sql_offset_in_the_store() -> None:
    hits = []
    for path in _py_files("store"):
        tree = _tree(path)
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            is_sql_string = (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            )
            if is_sql_string and re.search(r"\bOFFSET\b", node.value, re.IGNORECASE):  # type: ignore[attr-defined]
                hits.append(f"{_rel(path)}:{node.lineno}")  # type: ignore[attr-defined]
    assert not hits, "keyset pagination only (ADR-007): " + ", ".join(hits)


# --- D8: the stdlib HTTP clients import-linter cannot list -----------------------------------


def test_no_stdlib_http_client_outside_collect_and_match_llm() -> None:
    allowed = {"jobtracker/collect", "jobtracker/match/llm.py"}
    hits = []
    for path in _py_files():
        rel = str(path.relative_to(SRC.parent))
        if any(rel.startswith(a) for a in allowed):
            continue
        for node in ast.walk(_tree(path)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            hits += [
                f"{rel}:{node.lineno} {m}"
                for m in modules
                if m in {"urllib.request", "http.client"}
            ]
    assert not hits, "network clients live in collect/ and match/llm.py only: " + "; ".join(hits)


# --- interdit n°1: no threshold, weight or cadence literal in match/ --------------------------

_ALLOWED_NUMBERS = {0, 1, -1, 100}  # 0..100 is the score scale itself


def test_no_threshold_literal_in_match() -> None:
    """Every number that shapes a score or a tier comes from configs/profile.yaml."""
    hits = []
    for path in _py_files("match"):
        for node in ast.walk(_tree(path)):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, int | float)
                and not isinstance(node.value, bool)
                and node.value not in _ALLOWED_NUMBERS
            ):
                hits.append(f"{_rel(path)}:{node.lineno} {node.value!r}")
    assert not hits, "move these into configs/profile.yaml (interdit n°1): " + "; ".join(hits)


# --- interdit n°2: no swallowed errors ---------------------------------------------------------


def test_no_bare_except_and_no_except_pass() -> None:
    hits = []
    for path in _py_files():
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or _dotted(node.type) in {"Exception", "BaseException"}
            only_pass = all(isinstance(stmt, ast.Pass) for stmt in node.body)
            if node.type is None or (broad and only_pass) or only_pass:
                hits.append(f"{_rel(path)}:{node.lineno}")
    assert not hits, "an error must be visible, logged or re-raised: " + ", ".join(hits)


# --- registry coherence -----------------------------------------------------------------------


def test_every_source_has_a_collector_or_is_marked_unimplemented() -> None:
    from jobtracker.collect.base import UNIMPLEMENTED_SOURCES
    from jobtracker.runtime.scheduler import DEFAULT_COLLECTORS

    covered = set(DEFAULT_COLLECTORS) | UNIMPLEMENTED_SOURCES
    try:
        from jobtracker.collect.aggregators.setup import build

        covered |= {Source.ADZUNA, Source.EFC, Source.INDEED}
        assert build  # the aggregators package is present, so its three collectors count
    except ModuleNotFoundError:
        covered |= {Source.ADZUNA, Source.EFC, Source.INDEED}  # deletable package (WP13 §6)
    missing = set(Source) - covered
    assert not missing, f"no collector and not marked unimplemented: {sorted(missing)}"
    assert not (set(DEFAULT_COLLECTORS) & UNIMPLEMENTED_SOURCES), "marked unimplemented yet wired"


# --- stability of rejection identifiers --------------------------------------------------------

# Rejection reasons are persisted, shown in the UI and aggregated in the weekly report:
# renaming one silently splits its history. Changing this set is deliberate and visible.
_KNOWN_REJECTION_REASONS = {
    "excluded_title", "not_quant", "senior_only", "phd_required", "stale", "low_score",
}  # fmt: skip


def test_every_rejection_reason_match_can_produce_is_a_known_identifier() -> None:
    from jobtracker.match.rules import REJECTION_REASONS

    assert set(REJECTION_REASONS) == _KNOWN_REJECTION_REASONS
    produced: set[str] = set()
    for name in ("rules.py", "score.py"):
        for node in ast.walk(_tree(SRC / "match" / name)):
            if (
                isinstance(node, ast.Return)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                produced.add(node.value.value)
            if (
                isinstance(node, ast.keyword)
                and node.arg == "rejection_reason"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                produced.add(node.value.value)
            if isinstance(node, ast.IfExp):
                for branch in (node.body, node.orelse):
                    if isinstance(branch, ast.Constant) and isinstance(branch.value, str):
                        produced.add(branch.value)
    assert produced <= _KNOWN_REJECTION_REASONS, f"unknown: {produced - _KNOWN_REJECTION_REASONS}"
    assert produced == _KNOWN_REJECTION_REASONS, (
        f"never produced: {_KNOWN_REJECTION_REASONS - produced}"
    )


# --- rule C5: .env.example documents every variable Settings reads -------------------------------


def test_env_example_lists_every_setting() -> None:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    declared = set(re.findall(r"^#?\s*(JT_[A-Z0-9_]+)=", text, re.MULTILINE))
    expected = {f"JT_{name.upper()}" for name in Settings.model_fields}
    assert not expected - declared, f"missing from .env.example: {sorted(expected - declared)}"


def test_env_example_holds_placeholders_not_secrets() -> None:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    for name in ("JT_ADZUNA_APP_KEY", "JT_ADZUNA_APP_ID"):
        assert re.search(rf"^{name}=replace-me$", text, re.MULTILINE), name
    assert not re.search(r"^CLOUDFLARE_TUNNEL_TOKEN=.+", text, re.MULTILINE)


# --- persisted enums: a new value is a deliberate, visible change ------------------------------

_ENUM_SNAPSHOT = REPO_ROOT / "tests" / "fixtures" / "enum_snapshot.json"


def _persisted_enums() -> dict[str, list[str]]:
    from jobtracker.core import enums

    return {
        name: sorted(member.value for member in obj)
        for name, obj in vars(enums).items()
        if isinstance(obj, type) and issubclass(obj, enums.StrEnum) and obj is not enums.StrEnum
    }


def test_persisted_enum_values_only_change_deliberately() -> None:
    """Values are persisted and embedded in shareable URLs: add freely, never rename
    without a migration (blueprint core/enums.py). The snapshot makes either visible.
    """
    import json

    snapshot: dict[str, list[str]] = json.loads(_ENUM_SNAPSHOT.read_text(encoding="utf-8"))
    current = _persisted_enums()
    migrations = "\n".join(p.read_text() for p in (REPO_ROOT / "migrations").glob("*.sql"))
    problems = []
    for name, values in snapshot.items():
        for removed in sorted(set(values) - set(current.get(name, []))):
            if f"'{removed}'" not in migrations:
                problems.append(
                    f"{name}.{removed} was removed/renamed with no migration mentioning it"
                )
    for name, values in current.items():
        added = sorted(set(values) - set(snapshot.get(name, [])))
        if added:
            problems.append(f"{name} gained {added}: update tests/fixtures/enum_snapshot.json")
    assert not problems, "; ".join(problems)


@pytest.mark.parametrize(
    "name", ["Source", "Tier", "VisaStatus", "Seniority", "RoleFamily", "ApplicationStatus"]
)
def test_the_snapshot_covers_the_enums_that_reach_the_database(name: str) -> None:
    import json

    assert name in json.loads(_ENUM_SNAPSHOT.read_text(encoding="utf-8"))
