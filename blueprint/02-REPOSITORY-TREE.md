# 02 — Arborescence du dépôt

> Prérequis : [00-PRIMER.md](00-PRIMER.md), [01-ARCHITECTURE.md](01-ARCHITECTURE.md).
> À lire avant de créer un fichier. **Créer un fichier qui n'est pas dans cette
> liste demande de l'ajouter ici dans le même commit.**

---

## 1. Racine

```text
JobTracker/
├── CLAUDE.md                 # notes de session, commandes, conventions
├── README.md                 # présentation, mise en route
├── justfile                  # toutes les tâches de dev et d'exploitation
├── pyproject.toml            # dépendances, ruff, mypy, pytest, contrats import-linter
├── uv.lock
├── .env.example              # toutes les variables, valeurs factices
├── .gitignore
├── blueprint/                # CE dossier — la spécification
├── configs/                  # configuration versionnée (YAML)
├── migrations/               # SQL brut, NNNN_description.sql
├── src/jobtracker/           # le code Python
├── web/                      # le front
├── tests/                    # pytest + fixtures + corpus doré
├── tools/                    # scripts hors produit (sondes, modèles de charge)
├── spikes/                   # explorations jetables, exclues du lint
├── deploy/                   # compose de prod, systemd, tunnel, runbook
└── docs/                     # notes narratives non normatives
```

---

## 2. `src/jobtracker/`

### `core/` — socle partagé (WP01)

| Fichier | Responsabilité |
|---|---|
| `config.py` | `Settings` pydantic-settings : `.env` + `configs/*.yaml`. Point d'entrée unique de toute valeur configurable |
| `logging.py` | `structlog` JSON, `get_logger(name)`, injection du `run_id` par contexte |
| `errors.py` | Toute la taxonomie de [07-ERRORS-AND-LOGGING.md](07-ERRORS-AND-LOGGING.md). Aucune autre exception maison ailleurs |
| `db.py` | Connexion SQLite, pragmas WAL, `apply_migrations()`, gestionnaire de transaction |
| `models.py` | **Tous** les DTO `frozen` : `RawPosting`, `Posting`, `MatchVerdict`, `Company`, `SourceRun`, `Location`, `Compensation` |
| `enums.py` | `StrEnum` : `Source`, `Seniority`, `RoleFamily`, `VisaStatus`, `Tier`, `RemoteMode`, `SalaryPeriod` |
| `clock.py` | `utc_now()`, `freeze()` pour les tests. **Seule** source de temps du projet |
| `money.py` | `Money(amount: Decimal, currency: str)`, périodes, comparaison inter-devises explicite et datée |
| `geo.py` | Référentiel : ville → (pays ISO-3166, région, fuseau), alias (`NYC`→`New York`), normalisation |
| `hashing.py` | `content_hash()` (détection de changement), `fingerprint()` (dédoublonnage inter-sources) |
| `payloads.py` | Compression zstd de l'archive brute, `pack()` / `unpack()` |

### `store/` — persistance (WP02)

| Fichier | Responsabilité |
|---|---|
| `schema.py` | Chargement et vérification des migrations, version courante |
| `postings.py` | Dépôt des offres : upsert, lecture paginée keyset, mise à jour de verdict, aliasing |
| `companies.py` | Dépôt du registre matérialisé, compteurs par société |
| `runs.py` | Dépôt des runs de source : compteurs, durées, erreurs, état du disjoncteur |
| `facets.py` | Requêtes d'agrégation pour les filtres : comptes par pays, ville, société, séniorité, source, stack |
| `search.py` | Table FTS5, synchronisation par trigger, requêtes plein texte |
| `archive.py` | Écriture et relecture des charges utiles brutes compressées |
| `retention.py` | Purge et archivage selon [04-DATA-MODEL.md](04-DATA-MODEL.md) §6 |

### `collect/` — réseau (WP04, WP06, WP13)

| Fichier | Responsabilité |
|---|---|
| `base.py` | Le `Protocol` `Collector`, `CollectResult`, contrat de pagination |
| `http.py` | Politique HTTP unique : cadence, gigue, repli exponentiel, budget de requêtes, en-têtes, `User-Agent` |
| `registry.py` | Lecture de `configs/companies.yaml` → plan de collecte (société, source, jeton) |
| `ats/greenhouse.py` · `lever.py` · `ashby.py` | WP04 — les trois familles à endpoint JSON propre |
| `ats/workday.py` · `smartrecruiters.py` · `workable.py` · `recruitee.py` · `personio.py` | WP06 |
| `ats/custom.py` | WP06 — pages carrière réellement maison, une fonction par société, **en dernier recours** |
| `aggregators/efinancialcareers.py` · `wttj.py` · `linkedin.py` · `indeed.py` | **WP13 uniquement.** Isolés ici pour que leur suppression soit un `rm -rf` |

### `normalize/` — cascade déterministe (WP03)

| Fichier | Responsabilité |
|---|---|
| `cascade.py` | Orchestration des étages, produit `Posting`, trace l'étage résolveur |
| `title.py` | Nettoyage du titre, retrait des codes de req, détection de la famille de rôle |
| `location.py` | Texte libre → `Location(city, country, region, remote_mode)`. Multi-lieux, « Hybrid – 3 days » |
| `seniority.py` | Années d'expérience, niveaux, programmes graduate, internships |
| `compensation.py` | Fourchettes, devises, périodes (annuel/mensuel/journalier), bonus, equity |
| `visa.py` | Les trois états de [00-PRIMER.md](00-PRIMER.md) §2 (P4), avec l'extrait de texte qui justifie |
| `techstack.py` | Extraction de la stack : C++, Python, Rust, KDB/q, OCaml, CUDA, FPGA… |
| `dedup.py` | `fingerprint()` appliqué, détection d'alias, résolution ATS-canonique |
| `language.py` | Langue de l'annonce, et **langue exigée** si l'annonce le précise |

### `match/` — qualification (WP05, WP12)

| Fichier | Responsabilité |
|---|---|
| `profile.py` | Chargement de `configs/profile.yaml` en modèle typé |
| `rules.py` | Filtres durs : rôle hors périmètre, séniorité incompatible, doctorat exigé, offre périmée |
| `score.py` | Grille pondérée → `score` 0-100 et `tier` |
| `reasons.py` | Traçabilité : chaque point gagné ou perdu porte son motif, affiché dans l'UI |
| `prefilter.py` | **WP12** — préfiltre gratuit, zéro faux négatif par construction (invariant I3) |
| `llm.py` | **WP12** — unique module de `normalize`/`match` autorisé à faire de l'I/O |

### `api/` — FastAPI (WP07)

| Fichier | Responsabilité |
|---|---|
| `app.py` | Application, middlewares, CORS, gestionnaires d'erreurs |
| `deps.py` | Connexion en lecture, pagination, garde de santé |
| `schemas.py` | Modèles de réponse. **Distincts** des DTO internes : ils font partie du contrat public |
| `routers/postings.py` | `GET /postings`, `GET /postings/{id}`, `POST /postings/{id}/favorite`, `/hide` |
| `routers/facets.py` | `GET /facets` — comptes pour tous les filtres, calculés sous le filtre courant |
| `routers/companies.py` | `GET /companies` — registre et santé par société |
| `routers/health.py` | `GET /health` — état des sources, fraîcheur du flux, version du schéma |

### `runtime/` — exploitation (WP08, WP16)

| Fichier | Responsabilité |
|---|---|
| `cli.py` | `jobtracker migrate / run-once / loop / status / replay / report / probe` |
| `scheduler.py` | Cadence par source, gigue, fenêtres de collecte, priorités du registre |
| `breaker.py` | Disjoncteur par source : ouverture, demi-ouverture, fermeture |
| `watchdog.py` | Chien de garde **inversé** : alerte sur l'absence de résultat |
| `pipeline.py` | Câblage `collect → archive → normalize → match → store` |
| `replay.py` | **WP16** — rejeu du normaliseur sur l'archive, diff avant/après |
| `report.py` | **WP16** — rapport : couverture, sources muettes, taux de résolution par étage |

---

## 3. `configs/`

| Fichier | Contenu | Qui le modifie |
|---|---|---|
| `companies.yaml` | **Le registre.** Société → source, jeton, secteur, priorité, pays de référence | WP00, puis en continu |
| `profile.yaml` | Le profil cible : titres recherchés, titres exclus, poids de scoring, seuils de palier | WP05 |
| `sources.yaml` | Par famille de source : cadence, budget de requêtes, timeouts, activation | WP04, WP06, WP13 |
| `geo.yaml` | Alias de villes, groupements régionaux, correspondance ville → pays | WP01, WP03 |
| `taxonomy.yaml` | Familles de rôles, mots-clés de stack, marqueurs de séniorité | WP03, WP05 |

Aucune de ces valeurs n'a le droit d'apparaître en dur dans le code.

---

## 4. `web/`

```text
web/
├── openapi.json              # GÉNÉRÉ, commité
├── src/
│   ├── api/
│   │   ├── schema.gen.ts     # GÉNÉRÉ, commité — jamais édité à la main
│   │   ├── client.ts         # fetch typé, normalisation des erreurs
│   │   └── queries.ts        # hooks TanStack Query
│   ├── app/                  # routage, layout, providers, thème
│   ├── features/
│   │   ├── feed/             # liste virtualisée, carte d'offre, tri
│   │   ├── filters/          # panneau de facettes, état encodé dans l'URL
│   │   └── favorites/        # marquage et vue filtrée
│   ├── shared/
│   │   ├── ui/               # primitives shadcn + primitives de densité
│   │   └── lib/              # formatage de dates, devises, durées
│   └── mocks/                # handlers MSW, dérivés du schéma généré
└── tests/                    # vitest + RTL, e2e Playwright
```

---

## 5. `tests/`

```text
tests/
├── conftest.py
├── fixtures/
│   ├── postings/             # CORPUS DORÉ — offres réelles étiquetées à la main
│   │   ├── corpus.jsonl      # une offre + ses champs attendus par ligne
│   │   └── README.md         # comment étiqueter une nouvelle entrée
│   └── payloads/             # réponses figées par source, pour les tests de contrat
├── test_core_*.py
├── test_store_*.py
├── test_collect_*.py         # contrat : charges utiles figées, zéro réseau
├── test_normalize_*.py       # corpus doré + hypothesis
├── test_match_*.py
├── test_api_*.py
└── test_runtime_*.py
```

---

## 6. `tools/` et `spikes/`

| Chemin | Rôle |
|---|---|
| `tools/probe_ats.py` | **WP00** — sonde un jeton de board sur chaque famille d'ATS et rapporte lequel répond. L'outil qui construit le registre |
| `tools/llm_load.py` | **WP12** — modèle d'entonnoir : combien d'offres atteignent réellement le LLM, et combien de secondes de GPU par jour |
| `tools/label_corpus.py` | **WP00/WP14** — assistant d'étiquetage du corpus doré |
| `spikes/` | Explorations jetables. Exclu de `ruff` et de `mypy`. Rien d'importé par `src/` n'a le droit d'y vivre |
