# JobTracker

JobTracker monitors the quantitative finance job market. It collects postings from
about 300 hedge funds, trading firms, banks, asset managers and financial software
vendors, normalizes them into typed records, scores them against a target profile,
and serves them through a dense web interface.

The system collects, qualifies and displays. It does not apply on anyone's behalf.

## How it works

```text
collect → normalize → match → store → FastAPI → React
```

| Stage | Responsibility |
|---|---|
| **Collect** | One collector per ATS family (Greenhouse, Workday, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Personio), plus a configuration-driven collector for custom portals, read through a headless browser or their own JSON endpoints. Aggregators are optional and disabled by default. |
| **Normalize** | Turns raw payloads into structured postings: location, seniority, tech stack, compensation, visa status and a deduplication fingerprint. Performs no I/O, so it is fully testable offline. |
| **Match** | Applies a deterministic score against the profile in `configs/profile.yaml`. Additional searches are defined as tracks in `configs/tracks.yaml`. An optional local LLM resolves the ambiguous residue and reviews extracted fields, with each correction backed by a quotation from the posting. |
| **Store** | A single SQLite file with FTS5 search and a compressed archive of raw payloads. |
| **Serve** | A FastAPI backend with filters, facets and keyset pagination, and a React front end with a virtualized feed, a map, an application tracker and a health view. |

## Design principles

- **The company registry is the core asset.** `configs/companies.yaml` records which
  companies exist and which ATS each one uses. Adding a company is a configuration
  change, not new code.
- **ATS records are canonical.** A posting seen on an aggregator becomes an alias of the
  ATS record, never a duplicate.
- **Silent failures are treated as outages.** A dead board token returns zero postings
  rather than an error, so every stage that can go quiet has a counter and alerting.
- **Visa sponsorship has three states.** `sponsors`, `no` and `unknown` stay distinct, and
  `unknown` is never collapsed into either of the others.
- **Rejections are explicit.** A discarded posting always keeps a persisted reason.
- **Normalizer changes are measurable.** Raw payloads are archived so that any change can
  be replayed against past inputs and compared stage by stage.

## Tech stack

- **Backend:** Python 3.13, FastAPI, pydantic v2, SQLite, httpx, Playwright, structlog
- **Front end:** React 19, TypeScript, Vite, Tailwind CSS v4, TanStack Query and Virtual
- **Quality:** ruff, `mypy --strict`, import-linter, pytest, Hypothesis, Vitest, Playwright
- **Operations:** Docker Compose, nginx, Cloudflare Tunnel, systemd timers

## Getting started

Requires [uv](https://docs.astral.sh/uv/), [just](https://just.systems/) and Docker.

```bash
uv sync --all-extras
just browser-install     # Chromium for custom portals, once per machine
cp .env.example .env

just collect             # one pass over all enabled sources, writes ./data/jobtracker.db
just up                  # API and front end on http://127.0.0.1:5190
just down
```

Run `just collect` again to refresh the database. The interface picks up new data
without a restart. Use `just timers-install` to schedule collection with user-level
systemd timers.

## Configuration

| File | Purpose |
|---|---|
| `.env` | Paths, ports, LLM and aggregator switches |
| `configs/companies.yaml` | Company registry |
| `configs/sources.yaml` | Enabled sources and collection cadence |
| `configs/profile.yaml` | Target profile and scoring weights |
| `configs/tracks.yaml` | Additional search tracks |

The LLM is off by default and the pipeline runs fully without it. To enable it, set
`JT_LLM_ENABLED=true` and point `JT_LLM_BASE_URL` at a local OpenAI-compatible server
such as `llama-server`.

Personal data, including application history and CVs, stays under `data/`, which is
excluded from version control.

## Development

```bash
just api          # API on 127.0.0.1:8100
just web          # Vite dev server on 127.0.0.1:5190
just ci           # lint, architecture contracts, tests, front-end checks, API contract
just ci-full      # the above plus Playwright end-to-end tests
just              # list all tasks
```

Dependencies between packages are enforced by import-linter contracts. After changing an
API route or schema, run `just types` to regenerate the committed OpenAPI schema and
TypeScript client types.

## Deployment

The production stack runs on Docker Compose (collector, API, nginx) and is exposed over
HTTPS through a Cloudflare Tunnel, with no open inbound ports.

```bash
./scripts/deploy.sh
./scripts/backup.sh
./scripts/restore.sh <file>
```

See [`deploy/RUNBOOK.md`](deploy/RUNBOOK.md) for installation, upgrades, access protection
and incident procedures.

## Documentation

The design documentation is in [`blueprint/`](blueprint/README.md) and is written in
French. It covers the architecture, data model, interfaces, testing strategy and
architecture decisions.

## License

[MIT](LICENSE)
