# JobTracker

Agent de veille sur le marché de l'emploi quant. Il collecte les offres de
~400 sociétés de finance, les normalise, les qualifie contre un profil cible —
**quant developer junior, mobile à l'international** — et les sert dans un front
web dense où l'on scrolle, trie et filtre par pays, ville, société, séniorité,
stack et statut de sponsorship visa.

## Mise en route

```bash
uv sync --all-extras
cp .env.example .env
just migrate
just run-once source=greenhouse
just api        # API sur 127.0.0.1:8100
just web        # front sur 127.0.0.1:5190
```

Tâches de développement : `just lint`, `just arch`, `just test`,
`just test-golden`, `just ci`.

## Déploiement

Stack `docker compose` auto-hébergée (collecteur, API, nginx) derrière un tunnel
Cloudflare, sans port ouvert :

```bash
cp .env.example .env && $EDITOR .env
./scripts/deploy.sh          # build + up + attente que ça réponde
./scripts/backup.sh          # sauvegarde à chaud, vérifiée
./scripts/restore.sh <fichier>
```

Procédures complètes (installation, mise à jour, pannes, restauration, rotation des
secrets, **protection d'accès**) : [`deploy/RUNBOOK.md`](deploy/RUNBOOK.md).

## Architecture

Sept packages sous `src/jobtracker/`, contrats d'import vérifiés par
`import-linter` :

| Package | Rôle |
|---|---|
| `core` | config, logging, erreurs, base SQLite, DTO, horloge, monnaie, géo, hachage |
| `store` | migrations, dépôts, facettes, FTS5, archive brute, rétention |
| `collect` | un collecteur par **famille d'ATS**, politique HTTP commune |
| `normalize` | `RawPosting` → `Posting` : lieu, séniorité, stack, salaire, visa, empreinte. **Hors ligne** |
| `match` | scoring déterministe contre le profil ; `match.llm` pour le résidu ambigu |
| `api` | FastAPI en lecture : filtres, facettes, pagination keyset |
| `runtime` | ordonnanceur, disjoncteur, chien de garde inversé, CLI |

Front dans `web/` : React 19 + Vite + TypeScript strict + Tailwind v4 +
TanStack Query/Virtual.

Le LLM d'inférence est **local** (`llama-server` sur `127.0.0.1:8000`, partagé
avec OpenHands) : concurrence 1, décodage contraint par schéma, et le système
tourne entièrement sans lui.

## Documentation

- **[blueprint/](blueprint/)** — la spécification d'implémentation normative.
  Commencer par [blueprint/README.md](blueprint/README.md), puis
  [blueprint/00-PRIMER.md](blueprint/00-PRIMER.md).
- **[blueprint/dependencies.md](blueprint/dependencies.md)** — la matrice de
  parallélisation : quels lots peuvent être codés simultanément, et sur quels
  fichiers on se marche dessus.
- **[CLAUDE.md](CLAUDE.md)** — commandes, conventions, suivi du travail.

## État

Blueprint complet, socle du dépôt posé. Aucun lot de travail implémenté.
Prochaine étape : les trois racines sans prérequis — **WP00** (registre
d'entreprises), **WP01** (`core`), **WP09** (fondations du front) — qui peuvent
démarrer en parallèle.
