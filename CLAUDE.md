# JobTracker — notes for Claude Code

Monitoring agent for the **quant job market**. It collects postings from ~400 finance
companies (hedge funds, prop shops, banks, asset managers, vendors), normalizes them,
qualifies them against a target profile, **junior quant developer, 0-2 years, internationally
mobile**, and serves them in a dense web front end where you scroll, sort and filter by
country, city, company, seniority, stack and visa sponsorship status.

The chain: `collect` → `normalize` → `match` → `store` → FastAPI API → React front end. One
Python process, one SQLite file, one static front end.

**The product is the company registry and the normalizer, not the scraper.** A Greenhouse
collector is thirty lines and serves two hundred companies; knowing *which* companies exist
and *which* ATS each one uses is the project's asset. See
[`blueprint/00-PRIMER.md`](blueprint/00-PRIMER.md) §2.

## The chain, layer by layer

| Layer | Where | What it contains |
|---|---|---|
| Kernel | `src/jobtracker/core/` | config, logging, errors, SQLite database, pydantic DTOs, clock, money, hashing, geographic reference data |
| Persistence | `src/jobtracker/store/` | repositories per aggregate (`postings`, `companies`, `runs`), facet queries, FTS5 |
| Collection | `src/jobtracker/collect/` | one collector per **ATS family** (`ats/`), one per aggregator (`aggregators/`), shared HTTP policy; `custom.py` + `browser.py` read portals without an API as a **rendered page** (headless Chromium): a `source: custom` registry entry is the list URL (`token`) + the shape of a posting link (`extra.link`), or the portal's own JSON endpoint (`extra.api` + the field paths: Oracle HCM, Eightfold, BrassRing, in-house portals), no per-company code; `prefilter.py` decides which titles are worth a description request |
| Normalization | `src/jobtracker/normalize/` | `RawPosting` → `Posting`: location, seniority, stack, compensation, visa, deduplication fingerprint. **Zero I/O**, testable offline |
| Qualification | `src/jobtracker/match/` | deterministic score against the target profile; `match.llm` = prefilter + local LLM for the ambiguous residue only; **tracks** (`configs/tracks.yaml`): other searches scored against their own profile; `ch_tech` = C++ / CUDA / ML in Switzerland, `tech` = same + data science in well-paid countries (US, UK, DE, CH, JP…), `blueprint/wp/WP20-tracks.md` |
| API | `src/jobtracker/api/` | FastAPI: `/postings` (filters + sort + keyset pagination), `/facets`, `/map/pins`, `/companies`, `/health` |
| Operations | `src/jobtracker/runtime/` | scheduler, per-source circuit breaker, inverted watchdog, CLI |
| Front end | `web/src/` | React 19 + Vite + strict TypeScript + Tailwind v4 + TanStack Query/Virtual; tabs Feed, **Swiss tech** (track `ch_tech`, `/ch`), **Tech** (track `tech`, `/tech`: the same skills in well-paid countries), **Applications** (`/applications`: all applications, history, attachments, manual entry, `blueprint/wp/WP21-applications.md` §6), **Map** (local SVG, `blueprint/wp/WP17-map.md`), Companies, Health; application tracking (`blueprint/wp/WP18-tracking.md`) |
| Applications | `src/jobtracker/career/` | the history kept by hand (Sheet + screenshots folder) reconciled into `Application`; imports only `core` (D11). **Personal data under `data/career/`, never in the (public) repository**, `blueprint/wp/WP21-applications.md`; CV registry by content (`data/career/cvs/`), `blueprint/wp/WP22-cvs.md` |

The inference LLM is **local**: `llama-server` on `127.0.0.1:8000`, shared with OpenHands
(`~/AgenticEnv`). JobTracker attaches second, never with priority, concurrency 1,
schema-constrained decoding.

## Commands

| | |
|---|---|
| `just sync` | `uv sync --all-extras` |
| `just lint` | ruff check + format check + `mypy --strict`: **green before any commit** |
| `just arch` | `import-linter`: contracts D1→D9 of `blueprint/01-ARCHITECTURE.md` |
| `just test` | pytest, excluding the `live` marker |
| `just test-golden` | normalizer golden corpus, offline, with resolution rate per stage |
| `just migrate` | applies `migrations/*.sql` |
| `just run-once greenhouse` | one collection cycle on a family of sources |
| `just browser-install` | installs Chromium for `source: custom` boards: **once per machine**, after `just sync` |
| `just collect` | **one pass** over all enabled sources of `configs/sources.yaml`, then the LLM queue and the LLM review of new postings; writes to `./data/jobtracker.db` (exit code 1 if degraded) |
| `just up` / `just down` | the interface locally: API + front end in Docker (`docker-compose.yml`), on `http://127.0.0.1:5190`, reads `./data/jobtracker.db` |
| `just llm-enqueue` | queues the **already stored** postings the LLM can still help with (to do once, with the server on); then `just llm-drain --all` processes them to the end |
| `just llm-review` | the LLM **reviews all postings** and corrects salary, locations, seniority, visa, PhD, deadline; each correction requires a quotation found in the text; `--dry-run` writes nothing, `--limit N`, `--report f.jsonl` (`blueprint/wp/WP19-llm-review.md`) |
| `just llm-revert --field F` | cancels the LLM's corrections on a field: previous value restored, score recomputed, posting reread |
| `just import-applications <csv> <folder>` | application history: CSV export of the Sheet + `Company/Position/` folder (screenshots, CV sent) → `applications` table, attachments copied under `data/career/`; dry-run by default, `--apply`, `--report f.jsonl` (`blueprint/wp/WP21-applications.md`) |
| `just app …` | **manual** applications, without the pipeline: `app add --company X --title Y --url U` (or `--text posting.txt`, `--posting <id>`, `--attach cv.pdf`), `app status <id> interview`, `app list --open` (5 months without news = abandoned, nothing is stored), `app show/edit/link/attach/pdf/rm`; `app adopt-feed --apply` takes over the statuses set in the feed before WP21 |
| `just app cv …` | the CV registry (`blueprint/wp/WP22-cvs.md`): `app cv list`, `add <pdf> --label v3`, `label <id> <name> [--pin\|--unpin]`, `set <application> <cv\|none>`; `backfill` links applications to the CV in their folder, dry-run by default, `--apply`, `--report f.jsonl` |
| `just backup` | hot backup of `./data/jobtracker.db` and archive of `./data/career` in `./backups` |
| `just timers-install` / `timers-remove` | collection 3×/day + daily backup, **user** systemd timers (`deploy/local/`) |
| `just loop` | continuous scheduler |
| `just score-tracks` | scores stored postings against each track of `configs/tracks.yaml` (`collect` and `loop` do it on their own) |
| `just discover-employers` | employers seen on aggregators and absent from `companies.yaml` (feeds WP00) |
| `just replay <date>` | replay of the normalizer on archived inputs, **dry-run**: delta per stage, regression flagged |
| `just report` | weekly markdown report in `docs/reports/` |
| `./scripts/deploy.sh` · `backup.sh` · `restore.sh` | deployment of the production stack, hot backup, restore; see `deploy/RUNBOOK.md` |
| `just llm-drain` | one pass (20 postings) over the deferred LLM queue; `--all` = until the queue is empty or the server is lost |
| `just status` | health: silent sources, failing sources, feed freshness (exit code 1 if degraded) |
| `just api` | `uvicorn` on `127.0.0.1:8100` |
| `just web` | front end only, Vite on `127.0.0.1:5190` |
| `just types` | regenerates `web/openapi.json` + `web/src/api/schema.gen.ts` from FastAPI |
| `just web-check` / `just types-check` | front end (typecheck, lint, vitest, build + budget) / committed API contract = FastAPI's |
| `just e2e` | Playwright (journeys, axe, screenshots) on the compose stack + frozen demo database; `just e2e --update-snapshots` rewrites the screenshots |
| `just ci` | reproduces the `backend`, `frontend`, `api-contract` jobs: `lint arch test web-check types-check` |
| `just ci-full` | `ci` + `e2e` |

Rerun `just types` **after any API route or schema change**: both files are committed and the
CI job `api-contract` fails if the diff is not empty.

## Tracking work: GitHub Issues, no handoff markdown

The project's "JIRA" is the repository's **GitHub Issues**. `gh` is authenticated (account
`HadrienT`).

- **At the start of a session**: `gh issue list --state open`.
- **Issue handled** → `gh issue close <n> --comment "done in <sha>"`.
- **Never** a markdown handoff file between sessions. A task that outlives the session is an
  issue.
- Large pieces of **design** live in `blueprint/wp/*.md`; the issue points to them, it does not
  replace them.
- `blueprint/dependencies.md` holds the parallelization matrix: **consult it before starting a
  work package**, to check that its prerequisites are done and that no other session holds the
  same files.

## Reference documents

| File | Role |
|---|---|
| [`blueprint/README.md`](blueprint/README.md) | Index, table of work packages, dependency graph |
| [`blueprint/00-PRIMER.md`](blueprint/00-PRIMER.md) | Minimal complete context. **Read by every agent, without exception** |
| [`blueprint/09-CONVENTIONS.md`](blueprint/09-CONVENTIONS.md) | Conventions, units, Definition of Done. **Read before coding** |
| [`blueprint/10-PROFILE-TARGET.md`](blueprint/10-PROFILE-TARGET.md) | **The target**: the junior quant dev profile, the scoring grid, the role taxonomy |
| [`blueprint/11-SOURCES.md`](blueprint/11-SOURCES.md) | Source catalogue: ATS families, endpoints, company seed, legal status |
| [`blueprint/dependencies.md`](blueprint/dependencies.md) | Who can code what in parallel, and on which files people step on each other |
| [`blueprint/decisions.md`](blueprint/decisions.md) | ADRs: technical trade-offs and rejected alternatives |

## Conventions

- **Language: English by default.** Everything you produce is in English: code, identifiers, comments, commit messages, PRs, issues, documentation and interface text. The only exception is the conversation: reply in the language the maintainer writes in, so in French when they write in French. `blueprint/` and `docs/` are historically in French: new content there is in English too.
- **Commits: go through a branch, never directly on `main`.** End messages with
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Python 3.13**, `uv`, `ruff` (line length 100), `mypy --strict`, pydantic v2 DTOs with
  `frozen=True`, `structlog` JSON logging.
- **Money in `Decimal`**, never `float`. **Timezone-aware UTC `datetime` timestamps**, never
  `datetime.now()`: `core.clock.utc_now()` only.
- Any new parser comes with its case in the golden corpus (`tests/fixtures/postings/`), and
  preferably a **property** test rather than a simple equality.
- A discarded posting always carries a persisted **rejection reason**. Nothing is ever dropped
  silently.
- The **raw payload** of each posting is archived compressed. Without it, no normalizer
  improvement can be measured by replay.

## The project's permanent trap: the silent failure

A board token that turns 404 does not raise an error: it returns zero postings, and zero
postings looks exactly like "this company is not hiring right now". Every stage capable of going
quiet carries a counter, and the absence of results triggers a technical alert, not silence. See
[`blueprint/07-ERRORS-AND-LOGGING.md`](blueprint/07-ERRORS-AND-LOGGING.md) §4.

## Fragile sources: non-negotiable rule

LinkedIn, Indeed and the like are collected in the **last work package**, isolated in
`collect/aggregators/`, behind a configuration switch, and **the system must remain fully
functional with these sources disabled**. Their terms forbid scraping and their anti-bot
protection is aggressive: they would become the project's number one maintenance burden. They
bring only marginal coverage, as official ATSs carry most of the quant market. See
[`blueprint/wp/WP13-aggregators.md`](blueprint/wp/WP13-aggregators.md).

## Deployment

Self-hosted on the personal server, like `quant-modeling`: `docker compose` (collector + API +
nginx front end), exposed over HTTPS by a **Cloudflare tunnel**, no open port. Host ports are
configurable, `JT_API_PORT` (default 8100) and `JT_WEB_PORT` (default 5190), because several
projects run on the same machine. Copy `.env.example` to `.env`.

Classic Vite trap: `VITE_*` variables are **inlined at build time**, not read at runtime. The
front end reads its configuration from a `/config.js` injected by nginx at startup; do not
reintroduce an inlined `VITE_API_BASE`.
