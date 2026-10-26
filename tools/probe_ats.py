#!/usr/bin/env python3
"""Probe a company's career board across known ATS families.

See blueprint/wp/WP00-recon-registry.md and blueprint/11-SOURCES.md §2-3 for
the endpoints probed and the rules that govern this tool: never guess a token
into companies.yaml, a 200 with an empty list is "doubtful" and must never be
recorded as a success, and every host is hit sequentially with jitter.

Usage:
    uv run python tools/probe_ats.py --name "Optiver" --guess optiver
    uv run python tools/probe_ats.py --url https://www.optiver.com/working-at-optiver/career-opportunities/
    uv run python tools/probe_ats.py --in names.txt   # one company name per line
    uv run python tools/probe_ats.py --all --save
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "payloads"
COMPANIES_YAML = REPO_ROOT / "configs" / "companies.yaml"

# Operational defaults from blueprint/11-SOURCES.md §6. This is a standalone
# recon tool that predates configs/sources.yaml (owned by WP04); overridable
# via CLI flags rather than hardcoded business thresholds.
DEFAULT_USER_AGENT = "JobTracker-Probe/0.1 (+https://github.com/HadrienT/JobTracker)"
DEFAULT_TIMEOUT_S = 20.0
DEFAULT_JITTER_S = (2.0, 7.0)


class Family(StrEnum):
    """ATS family with a public, unauthenticated JSON (or XML) job list.

    Mirrors the relevant subset of core.enums.Source (blueprint/03-INTERFACES.md
    §1); duplicated here because tools/probe_ats.py must run standalone, ahead
    of and in parallel with WP01 (blueprint/dependencies.md §2, wave 1).
    """

    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    SMARTRECRUITERS = "smartrecruiters"
    WORKABLE = "workable"
    RECRUITEE = "recruitee"
    PERSONIO = "personio"
    # No collector of its own: a Pinpoint board is a `source: custom` entry reading
    # the tenant's postings.json through `extra.api` (format_yaml_entry writes it).
    PINPOINT = "pinpoint"


JSON_FAMILIES: tuple[Family, ...] = (
    Family.GREENHOUSE,
    Family.LEVER,
    Family.ASHBY,
    Family.SMARTRECRUITERS,
    Family.WORKABLE,
    Family.RECRUITEE,
    Family.PERSONIO,
    Family.PINPOINT,
)

# Some Pinpoint tenants that are not a real board (abandoned trials) answer 200 with
# seeded filler postings. Every one of them embeds Pinpoint's onboarding video under
# this doubled URL — a marker no real job description reproduces. Documented by
# career-ops' Pinpoint provider (issue #4190 there), MIT.
_PINPOINT_DEMO_MARKER = b"youtube.com/embed/https://www.youtube.com/embed/pFxm6fszrpw"


class Verdict(StrEnum):
    FOUND = "found"  # 200, non-empty list — a real board
    EMPTY = "empty"  # 200, empty list — doubtful (WP00 §2), never a success
    NOT_FOUND = "not_found"  # 404 — this candidate/family does not match
    BLOCKED = "blocked"  # 403/429 — back off, don't retry immediately
    ERROR = "error"  # network failure or payload that matches no known schema


@dataclass(frozen=True)
class ProbeResult:
    family: Family
    candidate: str
    verdict: Verdict
    job_count: int | None
    status_code: int | None
    url: str
    payload: bytes | None
    probed_at: datetime
    note: str = ""


def endpoint(family: Family, candidate: str) -> str:
    """Build the probe URL for a family/candidate pair (blueprint/11-SOURCES.md §2-3)."""
    if family is Family.GREENHOUSE:
        return f"https://boards-api.greenhouse.io/v1/boards/{candidate}/jobs?content=true"
    if family is Family.LEVER:
        return f"https://api.lever.co/v0/postings/{candidate}?mode=json"
    if family is Family.ASHBY:
        return f"https://api.ashbyhq.com/posting-api/job-board/{candidate}?includeCompensation=true"
    if family is Family.SMARTRECRUITERS:
        return (
            f"https://api.smartrecruiters.com/v1/companies/{candidate}/postings?limit=100&offset=0"
        )
    if family is Family.WORKABLE:
        return f"https://apply.workable.com/api/v1/widget/accounts/{candidate}?details=true"
    if family is Family.RECRUITEE:
        return f"https://{candidate}.recruitee.com/api/offers/"
    if family is Family.PERSONIO:
        return f"https://{candidate}.jobs.personio.de/xml"
    if family is Family.PINPOINT:
        return f"https://{candidate}.pinpointhq.com/postings.json"
    raise ValueError(f"unknown family: {family}")  # pragma: no cover — exhaustive above


def _job_count(family: Family, body: bytes) -> int | None:
    """Return the posting count in a 200 response, or None if the schema is unrecognized."""
    if family is Family.PERSONIO:
        if b"<workzag-jobs" in body or b"<position" in body:
            return body.count(b"<position>")
        return None
    try:
        data: Any = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if family is Family.GREENHOUSE:
        jobs = data.get("jobs") if isinstance(data, dict) else None
    elif family is Family.LEVER:
        jobs = data if isinstance(data, list) else None
    elif family is Family.ASHBY:
        jobs = data.get("jobs") if isinstance(data, dict) else None
    elif family is Family.SMARTRECRUITERS:
        jobs = data.get("content") if isinstance(data, dict) else None
    elif family is Family.WORKABLE:
        jobs = data.get("jobs") if isinstance(data, dict) else None
    elif family is Family.RECRUITEE:
        jobs = data.get("offers") if isinstance(data, dict) else None
    elif family is Family.PINPOINT:
        jobs = data.get("data") if isinstance(data, dict) else None
    else:  # pragma: no cover — exhaustive above
        jobs = None
    return len(jobs) if isinstance(jobs, list) else None


def slugify(name: str) -> str:
    """Turn a company name into a lowercase hyphenated slug guess."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def generate_candidates(name: str, guess: str | None = None) -> list[str]:
    """Generate plausible board-slug candidates for a company name, best guess first."""
    base = slugify(name)
    compact = base.replace("-", "")
    words = [w for w in base.split("-") if w]
    ordered: list[str] = []
    for candidate in (
        guess,
        base,
        compact,
        words[0] if words else None,
        "".join(words[:2]) if len(words) > 1 else None,
        f"{compact}us",
        f"{compact}global",
        f"{compact}group",
    ):
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def probe_one(client: httpx.Client, family: Family, candidate: str) -> ProbeResult:
    """Issue one probe request and classify the response. Never raises on HTTP failure."""
    url = endpoint(family, candidate)
    now = datetime.now(UTC)
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        return ProbeResult(
            family, candidate, Verdict.ERROR, None, None, url, None, now, note=str(exc)
        )
    if response.status_code == 404:
        return ProbeResult(family, candidate, Verdict.NOT_FOUND, None, 404, url, None, now)
    if response.status_code in (403, 429):
        return ProbeResult(
            family, candidate, Verdict.BLOCKED, None, response.status_code, url, None, now
        )
    if response.status_code != 200:
        return ProbeResult(
            family,
            candidate,
            Verdict.ERROR,
            None,
            response.status_code,
            url,
            None,
            now,
            note=f"unexpected status {response.status_code}",
        )
    count = _job_count(family, response.content)
    if count is None:
        return ProbeResult(
            family,
            candidate,
            Verdict.ERROR,
            None,
            200,
            url,
            response.content,
            now,
            note="200 but payload does not match the known schema for this family",
        )
    if family is Family.PINPOINT and _PINPOINT_DEMO_MARKER in response.content:
        return ProbeResult(
            family,
            candidate,
            Verdict.ERROR,
            None,
            200,
            url,
            None,
            now,
            note="Pinpoint demo tenant: seeded filler postings, not a real board",
        )
    verdict = Verdict.FOUND if count > 0 else Verdict.EMPTY
    return ProbeResult(family, candidate, verdict, count, 200, url, response.content, now)


def probe_company(
    client: httpx.Client,
    name: str,
    guess: str | None = None,
    families: Sequence[Family] = JSON_FAMILIES,
    jitter_s: tuple[float, float] = DEFAULT_JITTER_S,
) -> list[ProbeResult]:
    """Probe one company across families, sequentially, stopping at the first FOUND."""
    candidates = generate_candidates(name, guess)
    results: list[ProbeResult] = []
    for family in families:
        for candidate in candidates:
            result = probe_one(client, family, candidate)
            results.append(result)
            time.sleep(random.uniform(*jitter_s))
            if result.verdict is Verdict.FOUND:
                return results
    return results


# --- --url mode: look for an ATS fingerprint embedded in a career page --------

_URL_PATTERNS: dict[Family, re.Pattern[str]] = {
    Family.GREENHOUSE: re.compile(
        r"(?:boards-api|boards)\.greenhouse\.io/(?:v1/boards/|embed/job_board\?for=)?([a-z0-9_-]+)",
        re.I,
    ),
    Family.LEVER: re.compile(r"(?:api\.)?lever\.co/(?:v0/postings/)?([a-z0-9_-]+)", re.I),
    Family.ASHBY: re.compile(
        r"(?:api\.)?ashbyhq\.com/(?:posting-api/job-board/)?([a-z0-9_-]+)", re.I
    ),
    Family.SMARTRECRUITERS: re.compile(
        r"(?:careers|api)\.smartrecruiters\.com/(?:v1/companies/)?([a-z0-9_-]+)", re.I
    ),
    Family.WORKABLE: re.compile(
        r"apply\.workable\.com/(?:api/v1/widget/accounts/)?([a-z0-9_-]+)", re.I
    ),
    Family.RECRUITEE: re.compile(r"([a-z0-9_-]+)\.recruitee\.com", re.I),
    Family.PERSONIO: re.compile(r"([a-z0-9_-]+)\.jobs\.personio\.(?:de|com)", re.I),
}
WORKDAY_PATTERN = re.compile(
    r"([a-z0-9_-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/[a-z0-9_-]+/)?([a-z0-9_-]+)", re.I
)


# Portal families read through `source: custom` (blueprint/11-SOURCES.md §3): no
# collector of their own, but recognising one tells which `extra.api` recipe of the
# registry to copy (Oracle HCM: jpmorgan; Eightfold: millennium; Pinpoint:
# systematica) or that the board is a rendered listing. Host shapes follow the
# detect() rules of career-ops' providers (MIT).
_PORTAL_PATTERNS: dict[str, re.Pattern[str]] = {
    "oracle_hcm": re.compile(
        r"([a-z0-9-]+\.fa\.(?:[a-z0-9-]+\.)?(?:ocs\.)?oraclecloud(?:[1-9][0-9]?)?\.com)"
        r"/hcmUI/CandidateExperience/[a-z_-]+/sites/([a-z0-9_]+)",
        re.I,
    ),
    # app.eightfold.ai serves the widget's assets, on every tenant's page.
    "eightfold": re.compile(r"(?<![a-z0-9-])(?!app\.)([a-z0-9-]+)\.eightfold\.ai", re.I),
    "pinpoint": re.compile(r"([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\.pinpointhq\.com", re.I),
    "icims": re.compile(r"([a-z0-9-]+)\.icims\.com", re.I),
    "avature": re.compile(r"([a-z0-9-]+)\.avature\.net", re.I),
    "successfactors": re.compile(
        r"((?:[a-z0-9-]+\.)*(?:successfactors\.(?:eu|com)|jobs2web\.com))", re.I
    ),
    "taleo": re.compile(r"([a-z0-9-]+)\.taleo\.net", re.I),
    "teamtailor": re.compile(r"([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\.teamtailor\.com", re.I),
}


def find_portals(text: str) -> dict[str, set[str]]:
    """Portal families read through `source: custom` that a page's HTML points at."""
    hits: dict[str, set[str]] = {}
    for portal, pattern in _PORTAL_PATTERNS.items():
        found = {"/".join(g.lower() for g in m.groups()) for m in pattern.finditer(text)}
        if found:
            hits[portal] = found
    return hits


@dataclass(frozen=True)
class WorkdayHit:
    tenant: str
    wd: str
    site: str


def scan_career_page(
    client: httpx.Client, url: str
) -> tuple[dict[Family, set[str]], set[WorkdayHit], dict[str, set[str]]]:
    """Fetch a career page and search its HTML/inline scripts for ATS URL fingerprints."""
    response = client.get(url)
    response.raise_for_status()
    # The address itself, once redirects are followed, is a fingerprint too: a portal's
    # own page rarely spells out its absolute URL.
    text = f"{url}\n{response.url}\n{response.text}"
    hits: dict[Family, set[str]] = {}
    for family, pattern in _URL_PATTERNS.items():
        found = {m.group(1).lower() for m in pattern.finditer(text)}
        if found:
            hits[family] = found
    workday = {
        WorkdayHit(m.group(1), m.group(2), m.group(3)) for m in WORKDAY_PATTERN.finditer(text)
    }
    return hits, workday, find_portals(text)


# --- registry I/O ---------------------------------------------------------


def load_registry() -> list[dict[str, Any]]:
    if not COMPANIES_YAML.exists():
        return []
    data = yaml.safe_load(COMPANIES_YAML.read_text(encoding="utf-8")) or []
    if not isinstance(data, list):
        raise ValueError(f"{COMPANIES_YAML} must contain a YAML list")
    return data


def save_fixture(family: Family, slug: str, payload: bytes) -> Path:
    """Persist a captured payload under tests/fixtures/payloads/<family>/<slug>.json."""
    directory = FIXTURES_DIR / family.value
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{slug}.json"
    try:
        pretty = (
            json.dumps(json.loads(payload), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        )
        destination.write_text(pretty, encoding="utf-8")
    except json.JSONDecodeError:
        destination.write_bytes(payload)
    return destination


def format_yaml_entry(
    *,
    slug: str,
    name: str,
    sector: str,
    country: str,
    priority: int,
    result: ProbeResult | None,
) -> str:
    """Render a companies.yaml entry ready to paste, per blueprint/06-CONFIG.md §2."""
    today = datetime.now(UTC).date().isoformat()
    extra_lines: list[str] = []
    if result is not None and result.family is Family.PINPOINT:
        source = "custom"
        token = f"https://{result.candidate}.pinpointhq.com/"
        extra_lines = [
            "  extra:",
            f'    api: "{endpoint(Family.PINPOINT, result.candidate)}"',
            "    items: data",
            "    id: id",
            "    title: title",
            "    location: location.name",
            '    url: "{url}"',
            '    description: "description,key_responsibilities,'
            'skills_knowledge_expertise,benefits"',
        ]
    elif result is not None:
        source, token = result.family.value, result.candidate
    if result is not None and result.verdict is Verdict.FOUND:
        source_line = f"  source: {source}  # verified {today}"
        token_line = f'  token: "{token}"'
        enabled = "true"
    elif result is not None and result.verdict is Verdict.EMPTY:
        source_line = f"  source: {source}  # [À CONFIRMER] board vide au sondage du {today}"
        token_line = f'  token: "{token}"'
        enabled = "false"
    else:
        source_line = (
            f"  source: custom  # [À CONFIRMER] aucun ATS connu trouvé au sondage du {today}"
        )
        token_line = '  token: ""'
        enabled = "false"
    return "\n".join(
        [
            f"- slug: {slug}",
            f"  name: {name}",
            source_line,
            token_line,
            *extra_lines,
            f"  sector: {sector}",
            f"  hq_country: {country}",
            f"  priority: {priority}",
            f"  enabled: {enabled}",
        ]
    )


# --- CLI -------------------------------------------------------------------


def _build_client(timeout_s: float, user_agent: str) -> httpx.Client:
    return httpx.Client(
        timeout=timeout_s,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json, text/html;q=0.8, */*;q=0.5",
        },
        follow_redirects=True,
    )


def _print_results(results: Sequence[ProbeResult]) -> None:
    for r in results:
        print(
            f"  {r.family.value:<16} {r.candidate:<24} {r.verdict.value:<10} "
            f"jobs={r.job_count!s:<6} status={r.status_code} {r.note}",
            file=sys.stderr,
        )


def _run_name_mode(args: argparse.Namespace, client: httpx.Client) -> int:
    return _probe_and_print(args, client, args.name, guess=args.guess, slug=args.slug)


def _probe_and_print(
    args: argparse.Namespace,
    client: httpx.Client,
    name: str,
    *,
    guess: str | None,
    slug: str | None,
) -> int:
    results = probe_company(
        client, name, guess=guess, jitter_s=(args.jitter_min_s, args.jitter_max_s)
    )
    _print_results(results)
    found = next((r for r in results if r.verdict is Verdict.FOUND), None)
    if found is None:
        found = next((r for r in results if r.verdict is Verdict.EMPTY), None)
    if found is not None and args.save and found.payload is not None:
        dest = save_fixture(found.family, found.candidate, found.payload)
        print(f"# saved fixture: {dest.relative_to(REPO_ROOT)}", file=sys.stderr)
    print(
        format_yaml_entry(
            slug=slug or slugify(name).replace("-", "_"),
            name=name,
            sector=args.sector,
            country=args.country,
            priority=args.priority,
            result=found,
        )
    )
    return 0


def read_names(text: str) -> list[str]:
    """Company names of an `--in` file: one per line, blank lines and `#` comments skipped."""
    names = (line.split("#", 1)[0].strip() for line in text.splitlines())
    return [name for name in names if name]


def _run_batch_mode(args: argparse.Namespace, client: httpx.Client) -> int:
    known = {str(entry.get("name", "")).casefold() for entry in load_registry()}
    for name in read_names(Path(args.input).read_text(encoding="utf-8")):
        if name.casefold() in known:
            print(f"# {name}: already in companies.yaml, skipped", file=sys.stderr)
            continue
        print(f"# {name}", file=sys.stderr)
        _probe_and_print(args, client, name, guess=None, slug=None)
        print()
    return 0


def _run_url_mode(args: argparse.Namespace, client: httpx.Client) -> int:
    hits, workday_hits, portals = scan_career_page(client, args.url)
    if not hits and not workday_hits and not portals:
        print(
            "# no known ATS fingerprint found in this page — inspect the network tab by hand",
            file=sys.stderr,
        )
        return 1
    for family, candidates in hits.items():
        for candidate in sorted(candidates):
            print(f"  {family.value:<16} candidate={candidate}", file=sys.stderr)
    for wd in sorted(workday_hits, key=lambda w: (w.tenant, w.site)):
        print(f"  {'workday':<16} tenant={wd.tenant} wd={wd.wd} site={wd.site}", file=sys.stderr)
    for portal, matches in portals.items():
        for match in sorted(matches):
            print(f"  {portal:<16} custom portal={match}", file=sys.stderr)
    return 0


def _run_all_mode(args: argparse.Namespace, client: httpx.Client) -> int:
    registry = load_registry()
    degraded = 0
    for entry in registry:
        if not entry.get("enabled", False):
            continue
        try:
            family = Family(entry["source"])
        except ValueError:
            continue  # workday / custom: not re-probed by this simple loop
        result = probe_one(client, family, entry["token"])
        time.sleep(random.uniform(args.jitter_min_s, args.jitter_max_s))
        status = "OK" if result.verdict is Verdict.FOUND else "DEGRADED"
        if status == "DEGRADED":
            degraded += 1
        print(
            f"{status:<9} {entry['slug']:<28} {family.value:<16} "
            f"{result.verdict.value} jobs={result.job_count}"
        )
        if args.save and result.payload is not None:
            save_fixture(family, entry["token"], result.payload)
    if degraded:
        print(
            f"\n{degraded} board(s) no longer resolve — investigate before trusting the feed.",
            file=sys.stderr,
        )
    return 1 if degraded else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--name", help="company name to probe (generates slug candidates)")
    mode.add_argument("--url", help="career page URL to scan for an embedded ATS fingerprint")
    mode.add_argument(
        "--in",
        dest="input",
        help="file of company names, one per line: probe each one absent from the registry",
    )
    mode.add_argument(
        "--all", action="store_true", help="re-probe every enabled entry in configs/companies.yaml"
    )
    parser.add_argument("--guess", help="a specific board slug/token to try first, with --name")
    parser.add_argument("--slug", help="override the generated company_slug in the YAML output")
    parser.add_argument(
        "--sector", default="unknown", help="sector tag for the generated companies.yaml line"
    )
    parser.add_argument(
        "--country", default="XX", help="ISO-3166 alpha-2 HQ country for the generated line"
    )
    parser.add_argument("--priority", type=int, default=2, help="registry priority (1-3)")
    parser.add_argument(
        "--save", action="store_true", help="persist the captured payload as a fixture"
    )
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--jitter-min-s", type=float, default=DEFAULT_JITTER_S[0])
    parser.add_argument("--jitter-max-s", type=float, default=DEFAULT_JITTER_S[1])
    args = parser.parse_args(argv)

    with _build_client(args.timeout_s, args.user_agent) as client:
        if args.name:
            return _run_name_mode(args, client)
        if args.url:
            return _run_url_mode(args, client)
        if args.input:
            return _run_batch_mode(args, client)
        return _run_all_mode(args, client)


if __name__ == "__main__":
    raise SystemExit(main())
