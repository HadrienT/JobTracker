# JobTracker — notes pour Claude Code

Agent de veille sur le **marché de l'emploi quant**. Il collecte les offres de
~400 sociétés de finance (hedge funds, prop shops, banques, asset managers,
éditeurs), les normalise, les qualifie contre un profil cible — **quant
developer junior, 0-2 ans, mobile à l'international** — et les sert dans un
front web dense où l'on scrolle, trie et filtre par pays, ville, société,
séniorité, stack et statut de sponsorship visa.

La chaîne : `collect` → `normalize` → `match` → `store` → API FastAPI → front
React. Un processus Python, un fichier SQLite, un front statique.

**Le produit, c'est le registre d'entreprises et le normaliseur, pas le
scraper.** Un collecteur Greenhouse fait trente lignes et sert deux cents
sociétés ; savoir *quelles* sociétés existent et *quel* ATS chacune utilise est
l'actif du projet. Voir [`blueprint/00-PRIMER.md`](blueprint/00-PRIMER.md) §2.

## La chaîne, couche par couche

| Couche | Où | Ce qu'elle contient |
|---|---|---|
| Noyau | `src/jobtracker/core/` | config, logging, erreurs, base SQLite, DTO pydantic, horloge, monnaie, hachage, référentiel géographique |
| Persistance | `src/jobtracker/store/` | dépôts par agrégat (`postings`, `companies`, `runs`), requêtes de facettes, FTS5 |
| Collecte | `src/jobtracker/collect/` | un collecteur par **famille d'ATS** (`ats/`), un par agrégateur (`aggregators/`), politique HTTP commune |
| Normalisation | `src/jobtracker/normalize/` | `RawPosting` → `Posting` : lieu, séniorité, stack, rémunération, visa, empreinte de dédoublonnage. **Zéro I/O**, testable hors ligne |
| Qualification | `src/jobtracker/match/` | score déterministe contre le profil cible ; `match.llm` = préfiltre + LLM local pour le seul résidu ambigu |
| API | `src/jobtracker/api/` | FastAPI : `/postings` (filtres + tri + pagination keyset), `/facets`, `/companies`, `/health` |
| Exploitation | `src/jobtracker/runtime/` | ordonnanceur, disjoncteur par source, chien de garde inversé, CLI |
| Front | `web/src/` | React 19 + Vite + TypeScript strict + Tailwind v4 + TanStack Query/Virtual |

Le LLM d'inférence est **local** : `llama-server` sur `127.0.0.1:8000`, partagé
avec OpenHands (`~/AgenticEnv`). JobTracker s'y greffe en second, jamais en
priorité, concurrence 1, décodage contraint par schéma.

## Commandes

| | |
|---|---|
| `just sync` | `uv sync --all-extras` |
| `just lint` | ruff check + format check + `mypy --strict` — **vert avant tout commit** |
| `just arch` | `import-linter` : contrats D1→D9 de `blueprint/01-ARCHITECTURE.md` |
| `just test` | pytest, hors marqueur `live` |
| `just test-golden` | corpus doré du normaliseur, hors ligne, avec taux de résolution par étage |
| `just migrate` | applique `migrations/*.sql` |
| `just run-once source="greenhouse"` | un cycle de collecte sur une famille de sources |
| `just loop` | ordonnanceur continu |
| `just discover-employers` | employeurs vus chez les agrégateurs et absents de `companies.yaml` (alimente WP00) |
| `just llm-drain` | un passage sur la file LLM différée (le serveur est partagé et pas toujours levé) |
| `just status` | santé : sources muettes, sources en erreur, fraîcheur du flux (code retour 1 si dégradé) |
| `just api` | `uvicorn` sur `127.0.0.1:8100` |
| `just web` | front seul, Vite sur `127.0.0.1:5190` |
| `just types` | régénère `web/openapi.json` + `web/src/api/schema.gen.ts` depuis FastAPI |
| `just ci` | reproduit la CI locale : `lint arch test` |

`just types` est à relancer **après tout changement de route ou de schéma API** :
les deux fichiers sont commités et le job CI `api-contract` échoue si le diff
n'est pas vide.

## Suivi du travail — GitHub Issues, pas de markdown de handoff

Le « JIRA » du projet, ce sont les **GitHub Issues du repo**. `gh` est
authentifié (compte `HadrienT`).

- **Au démarrage d'une session** : `gh issue list --state open`.
- **Issue traitée** → `gh issue close <n> --comment "fait dans <sha>"`.
- **Jamais** de fichier markdown de passation entre sessions. Une tâche qui
  survit à la session est une issue.
- Les gros morceaux de **conception** vivent dans `blueprint/wp/*.md` ; l'issue
  y renvoie, elle ne les remplace pas.
- `blueprint/dependencies.md` porte la matrice de parallélisation : **le
  consulter avant de démarrer un lot**, pour vérifier que ses prérequis sont
  faits et qu'aucune autre session ne tient les mêmes fichiers.

## Documents de référence

| Fichier | Rôle |
|---|---|
| [`blueprint/README.md`](blueprint/README.md) | Index, table des lots de travail, graphe de dépendances |
| [`blueprint/00-PRIMER.md`](blueprint/00-PRIMER.md) | Contexte minimal complet. **Lu par tout agent, sans exception** |
| [`blueprint/09-CONVENTIONS.md`](blueprint/09-CONVENTIONS.md) | Conventions, unités, Definition of Done. **Lu avant de coder** |
| [`blueprint/10-PROFILE-TARGET.md`](blueprint/10-PROFILE-TARGET.md) | **La cible** : le profil quant dev junior, la grille de scoring, la taxonomie des rôles |
| [`blueprint/11-SOURCES.md`](blueprint/11-SOURCES.md) | Catalogue des sources : familles d'ATS, endpoints, seed d'entreprises, statut légal |
| [`blueprint/dependencies.md`](blueprint/dependencies.md) | Qui peut coder quoi en parallèle, et sur quels fichiers on se marche dessus |
| [`blueprint/decisions.md`](blueprint/decisions.md) | ADR : arbitrages techniques et alternatives rejetées |

## Conventions

- **Conversation avec le mainteneur : en français.** Code, identifiants,
  commentaires, messages de commit, **interface du front** : en anglais.
  `blueprint/` et `docs/` sont en français.
- **Commits : passer par une branche, jamais directement sur `main`.** Terminer
  les messages par `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Python 3.13**, `uv`, `ruff` (ligne 100), `mypy --strict`, DTO `pydantic` v2
  `frozen=True`, journalisation `structlog` en JSON.
- **Argent en `Decimal`**, jamais `float`. **Horodatages `datetime` aware UTC**,
  jamais `datetime.now()` — `core.clock.utc_now()` uniquement.
- Tout nouveau parseur arrive avec son cas dans le corpus doré
  (`tests/fixtures/postings/`), et de préférence un test de **propriété** plutôt
  qu'une simple égalité.
- Une offre écartée porte toujours un **motif de rejet** persisté. On ne jette
  jamais silencieusement.
- La **charge utile brute** de chaque offre est archivée compressée. Sans elle,
  aucune amélioration du normaliseur n'est mesurable par rejeu.

## Le piège permanent du projet : la panne silencieuse

Un jeton de board qui passe en 404 ne lève pas d'erreur : il renvoie zéro offre,
et zéro offre ressemble exactement à « cette société ne recrute pas en ce
moment ». Tout étage capable de se taire porte un compteur, et l'absence de
résultat déclenche une alerte technique — pas un silence. Voir
[`blueprint/07-ERRORS-AND-LOGGING.md`](blueprint/07-ERRORS-AND-LOGGING.md) §4.

## Sources fragiles — règle non négociable

LinkedIn, Indeed et consorts sont collectés en **dernier lot**, isolés dans
`collect/aggregators/`, derrière un interrupteur de configuration, et **le
système doit rester pleinement fonctionnel avec ces sources désactivées**. Leurs
CGU interdisent le scraping et leur anti-bot est agressif : elles deviendront la
source n°1 de maintenance du projet. Elles n'apportent que de la couverture
marginale — les ATS officiels portent l'essentiel du marché quant. Voir
[`blueprint/wp/WP13-aggregators.md`](blueprint/wp/WP13-aggregators.md).

## Déploiement

Auto-hébergé sur le serveur perso, comme `quant-modeling` : `docker compose`
(collecteur + API + front nginx), exposé en HTTPS par un **tunnel Cloudflare**,
aucun port ouvert. Les ports hôte sont paramétrables — `JT_API_PORT` (défaut
8100) et `JT_WEB_PORT` (défaut 5190) — parce que plusieurs projets tournent sur
la même machine. Copier `.env.example` en `.env`.

Piège Vite classique : les variables `VITE_*` sont **inlinées au build**, pas
lues au runtime. Le front lit sa configuration depuis un `/config.js` injecté
par nginx au démarrage — ne pas réintroduire de `VITE_API_BASE` inliné.
