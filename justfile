# JobTracker — tâches de développement et d'exploitation
set shell := ["bash", "-uc"]
set dotenv-load := true

# liste les tâches
default:
    @just --list

# installe l'environnement
sync:
    uv sync --all-extras

# lint + format check + typage
lint:
    uv run ruff check src tests tools
    uv run ruff format --check src tests tools
    uv run mypy

# formate le code
fmt:
    uv run ruff format src tests tools
    uv run ruff check --fix src tests tools

# contrats d'architecture D1→D9
arch:
    uv run lint-imports

# tous les tests sauf @live
test:
    uv run pytest

# corpus doré + tableau de résolution par étage
test-golden:
    uv run pytest -m golden -q -s

# tests de propriété (hypothesis, invariants I1→I3)
test-property:
    uv run pytest -m property -q

# applique les migrations
migrate:
    uv run jobtracker migrate

# un cycle de collecte sur une famille de sources
run-once source="greenhouse":
    uv run jobtracker run-once --source {{source}}

# un passage sur toutes les sources activées (configs/sources.yaml), puis la file LLM ; code 1 si dégradé
collect:
    uv run jobtracker collect

# l'interface en local : API + front dans docker, sur http://127.0.0.1:5190 (lit ./data/jobtracker.db)
up:
    mkdir -p data
    HOST_UID=$(id -u) HOST_GID=$(id -g) docker compose up -d --build --wait
    @echo "http://127.0.0.1:${JT_WEB_PORT:-5190}"

down:
    docker compose down

# ordonnanceur continu
loop:
    uv run jobtracker loop

# un passage sur la file LLM différée (serveur occupé/éteint = tour sauté)
llm-drain:
    uv run jobtracker llm-drain

# employeurs vus chez les agrégateurs et absents de companies.yaml (alimente WP00)
discover-employers:
    uv run jobtracker discover-employers

# santé : sources muettes, fraîcheur du flux (code retour 1 si dégradé)
status:
    uv run jobtracker status

# sonde une société pour trouver son ATS et son jeton
probe company:
    uv run python tools/probe_ats.py --name {{company}}

# rejeu du normaliseur sur l'archive brute
replay since:
    uv run jobtracker replay --since {{since}} --dry-run

# rapport hebdomadaire
report:
    uv run jobtracker report --weekly

# API
api:
    uv run uvicorn jobtracker.api.app:app --host ${JT_API_HOST:-127.0.0.1} --port ${JT_API_PORT:-8100} --reload

# front seul
web:
    cd web && npm run dev

# régénère web/openapi.json + web/src/api/schema.gen.ts
types:
    uv run python tools/gen_openapi.py web/openapi.json
    cd web && npm run api:types:local

# sauvegarde de la base (jamais `cp` sur une base WAL)
backup db="jobtracker.db":
    mkdir -p backups
    sqlite3 {{db}} ".backup backups/jobtracker-$(date +%Y%m%d).db"

# le front : types, lint, tests unitaires, build + budget de bundle
web-check:
    cd web && npm run typecheck && npm run lint && npm run test -- --run && npm run build

# le contrat d'API commité doit être celui que FastAPI génère
types-check: types
    git diff --exit-code web/openapi.json web/src/api/schema.gen.ts

# parcours navigateur + axe + captures, sur la stack compose et une base de démo figée
# (`just e2e --update-snapshots` réécrit les captures de référence)
e2e *args:
    scripts/e2e.sh {{args}}

# CI locale : reproduit les trois premiers jobs de .github/workflows/ci.yml (backend, frontend, api-contract)
ci: lint arch test web-check types-check

# tout, e2e compris — ce que la CI exécute au total
ci-full: ci e2e
