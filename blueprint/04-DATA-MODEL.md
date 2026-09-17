# 04 — Modèle de données

> Prérequis : [00-PRIMER.md](00-PRIMER.md), [03-INTERFACES.md](03-INTERFACES.md).
> À lire si vous touchez la base. **Propriétaire : WP02.**

SQLite, journal **WAL**, un fichier `jobtracker.db`. Migrations en SQL brut
versionné dans `migrations/NNNN_description.sql`, appliquées par
`jobtracker migrate`, jamais à la main.

---

## 1. Vue d'ensemble

```text
companies ──┬─< postings ──┬─< posting_aliases
            │              ├─< posting_locations
            │              ├── verdicts          (1-1)
            │              ├─< posting_tech
            │              └── raw_payloads      (1-1, archive compressée)
            └─< source_runs

postings_fts  (FTS5, synchronisée par triggers)
user_flags    (favori, masqué — la seule table que l'API écrit)
schema_version
```

---

## 2. Tables

### `companies`

Matérialisation de `configs/companies.yaml`, rafraîchie à chaque démarrage.
La configuration reste la source de vérité ; la table sert aux jointures et aux
comptes.

| Colonne | Type | Note |
|---|---|---|
| `company_slug` | TEXT PK | `jane_street` |
| `company_name` | TEXT NOT NULL | |
| `source` | TEXT NOT NULL | |
| `token` | TEXT NOT NULL | |
| `sector` | TEXT NOT NULL | |
| `hq_country` | TEXT NOT NULL | ISO-3166 alpha-2 |
| `priority` | INTEGER NOT NULL | 1 → 3 |
| `enabled` | INTEGER NOT NULL | booléen |
| `last_ok_at` | TEXT | ISO-8601 UTC, dernière collecte réussie |
| `last_count` | INTEGER | offres remontées au dernier passage — **le compteur de P3** |

### `postings`

| Colonne | Type | Note |
|---|---|---|
| `posting_id` | TEXT PK | ULID — trié par date de création, contrairement à un UUID v4 |
| `fingerprint` | TEXT NOT NULL | clé de dédoublonnage, **non unique** (un alias la partage) |
| `is_canonical` | INTEGER NOT NULL | 1 pour l'offre affichée, 0 pour une republication rétrogradée |
| `source` | TEXT NOT NULL | |
| `company_slug` | TEXT NOT NULL REFERENCES companies | |
| `source_job_id` | TEXT NOT NULL | |
| `url` | TEXT NOT NULL | |
| `title` | TEXT NOT NULL | nettoyé |
| `title_raw` | TEXT NOT NULL | conservé : le nettoyage est une hypothèse, pas une vérité |
| `role_family` | TEXT NOT NULL | |
| `seniority` | TEXT NOT NULL | |
| `min_years` | INTEGER | **NULL = non dit**, jamais 0 par défaut |
| `phd_required` | INTEGER NOT NULL | |
| `visa_sponsorship` | TEXT NOT NULL | `sponsors` / `no` / `unknown` |
| `visa_evidence` | TEXT | l'extrait qui justifie — affiché au survol dans l'UI |
| `salary_min`, `salary_max` | TEXT | **`Decimal` sérialisé en TEXT**, jamais REAL |
| `salary_currency` | TEXT | ISO-4217 |
| `salary_period` | TEXT | |
| `posted_at` | TEXT | NULL si la source ne le donne pas |
| `first_seen_at` | TEXT NOT NULL | |
| `last_seen_at` | TEXT NOT NULL | |
| `closes_at` | TEXT | fenêtre de campagne graduate |
| `content_hash` | TEXT NOT NULL | détecte un changement de contenu sans rescorer inutilement |
| `normalize_version` | INTEGER NOT NULL | permet un rejeu ciblé (WP16) |
| `is_active` | INTEGER NOT NULL | passe à 0 quand l'offre disparaît du board |

`UNIQUE (source, company_slug, source_job_id)` — la clé naturelle de la source.

**`salary_*` en TEXT, pas en REAL.** SQLite n'a pas de type décimal ; stocker un
montant en `REAL` fait rentrer un flottant binaire dans une chaîne monétaire, ce
que le PRIMER interdit. On sérialise le `Decimal` et on le relit tel quel. Le tri
par salaire se fait côté SQL avec `CAST(salary_min AS REAL)` — acceptable pour
**ordonner**, jamais pour calculer.

### `posting_locations`

Une offre peut être publiée sur plusieurs sites. Une table séparée, parce qu'un
filtre par ville doit rester un index, pas un `LIKE` sur une chaîne concaténée.

| Colonne | Type |
|---|---|
| `posting_id` | TEXT NOT NULL REFERENCES postings ON DELETE CASCADE |
| `city` | TEXT |
| `country` | TEXT |
| `region` | TEXT |
| `remote_mode` | TEXT NOT NULL |
| `raw` | TEXT |

### `posting_tech`

`(posting_id, tech)`, PK composite. Même raison : un filtre « C++ **et** Python »
est une jointure, pas une regex.

### `verdicts`

| Colonne | Type | Note |
|---|---|---|
| `posting_id` | TEXT PK REFERENCES postings ON DELETE CASCADE | |
| `score` | INTEGER NOT NULL | 0 → 100 |
| `tier` | TEXT NOT NULL | |
| `rejection_reason` | TEXT | NOT NULL ⟺ `tier='rejected'` (invariant I5) |
| `reasons_json` | TEXT NOT NULL | les `Reason[]` sérialisés — affichés dans le détail |
| `profile_version` | INTEGER NOT NULL | permet de rescorer uniquement ce qui est périmé |
| `scored_at` | TEXT NOT NULL | |

### `posting_aliases`

La table qui rend le flux lisible (principe P2).

| Colonne | Type | Note |
|---|---|---|
| `canonical_id` | TEXT NOT NULL REFERENCES postings | |
| `source` | TEXT NOT NULL | |
| `source_job_id` | TEXT NOT NULL | |
| `url` | TEXT NOT NULL | l'UI propose « aussi sur LinkedIn » |
| `seen_at` | TEXT NOT NULL | |

`UNIQUE (source, source_job_id)`.

### `raw_payloads`

| Colonne | Type | Note |
|---|---|---|
| `posting_id` | TEXT PK | |
| `payload_zstd` | BLOB NOT NULL | la charge utile d'origine, **jamais jetée** avant la rétention |
| `fetched_at` | TEXT NOT NULL | |

C'est la table qui rend WP16 possible. Sans elle, « j'ai amélioré le parseur de
séniorité » est une affirmation invérifiable.

### `source_runs`

| Colonne | Type | Note |
|---|---|---|
| `run_id` | TEXT NOT NULL | ULID, partagé par tous les logs du cycle |
| `source` | TEXT NOT NULL | |
| `company_slug` | TEXT | NULL pour un run agrégé |
| `started_at`, `ended_at` | TEXT NOT NULL | |
| `fetched`, `new`, `updated`, `aliased`, `rejected` | INTEGER NOT NULL | **les compteurs de P3** |
| `requests_made` | INTEGER NOT NULL | |
| `status` | TEXT NOT NULL | `ok` / `empty` / `error` / `blocked` / `skipped` |
| `error_kind` | TEXT | issu de la taxonomie de [07-ERRORS-AND-LOGGING.md](07-ERRORS-AND-LOGGING.md) |

**`empty` est un statut distinct de `ok`.** Un run qui remonte zéro offre n'est
pas un succès : c'est l'événement que le chien de garde surveille.

### `user_flags`

La **seule** table que l'API écrit.

| Colonne | Type |
|---|---|
| `posting_id` | TEXT PK REFERENCES postings ON DELETE CASCADE |
| `is_favorite` | INTEGER NOT NULL DEFAULT 0 |
| `is_hidden` | INTEGER NOT NULL DEFAULT 0 |
| `updated_at` | TEXT NOT NULL |

Séparée de `postings` exprès : le pipeline réécrit `postings` en permanence, et
un favori ne doit **jamais** pouvoir être écrasé par une passe de normalisation.

---

## 3. Recherche plein texte

```sql
CREATE VIRTUAL TABLE postings_fts USING fts5(
    title, company_name, description, tech,
    content='',              -- table externe : on ne duplique pas la description
    tokenize='unicode61 remove_diacritics 2'
);
```

Synchronisée par triggers `AFTER INSERT / UPDATE / DELETE` sur `postings`.
`remove_diacritics 2` est obligatoire : le flux est multilingue, et
« Développeur » doit se trouver en tapant « developpeur ».

La description complète vit dans FTS et **pas** dans `postings` : la colonne
serait lourde, jamais lue par le flux, et lue seulement dans le détail — où elle
se relit depuis `raw_payloads` ou depuis FTS.

---

## 4. Index

| Index | Colonnes | Sert à |
|---|---|---|
| `idx_postings_feed` | `(is_canonical, is_active, tier, score DESC, posting_id DESC)` | le tri par défaut du flux, en keyset |
| `idx_postings_posted` | `(is_canonical, is_active, posted_at DESC, posting_id DESC)` | tri « plus récentes » |
| `idx_postings_fingerprint` | `(fingerprint)` | dédoublonnage à l'insertion |
| `idx_postings_company` | `(company_slug, is_active)` | page société, comptes |
| `idx_locations_country` | `(country, city)` | filtres et facettes géographiques |
| `idx_tech` | `(tech, posting_id)` | filtre par stack |
| `idx_runs_source` | `(source, started_at DESC)` | santé, chien de garde |

**Le tri par défaut inclut `posting_id` en second critère.** Sans ce
départageur, deux offres au même score rendent la pagination keyset
non-déterministe, et on saute ou on répète des lignes entre deux pages — un bug
qui ne se voit qu'après avoir scrollé trois écrans, donc jamais en test manuel.

---

## 5. Migrations

- `migrations/0001_initial.sql`, `0002_*.sql`… Numérotation contiguë, jamais
  réutilisée, jamais réécrite après un commit sur `main`.
- Chaque migration est **idempotente à la relecture** (`IF NOT EXISTS`) et
  contient son propre `INSERT INTO schema_version`.
- Une migration destructrice (`DROP COLUMN`, changement de type) se fait par
  table de remplacement + copie + bascule, jamais en place. SQLite supporte mal
  le reste.
- Aucune migration ne recalcule de donnée métier. Un rescoring est un
  **rejeu** (`jobtracker replay`), pas une migration.

---

## 6. Rétention

| Donnée | Durée | Raison |
|---|---|---|
| `postings` actives | indéfinie | le volume est dérisoire — quelques dizaines de milliers de lignes |
| `postings` inactives | 180 jours | permet de voir la saisonnalité des campagnes graduate |
| `raw_payloads` | **365 jours** | c'est le corpus de rejeu ; le garder longtemps est l'intérêt même du projet |
| `raw_payloads` d'offres rejetées en `not_quant` | 90 jours | volume important, valeur de rejeu faible |
| `source_runs` | 90 jours | au-delà, seules les agrégations servent |
| `user_flags` | **jamais purgés** | un favori survit à la disparition de l'offre |

Ordre de grandeur attendu : 400 sociétés × ~40 offres visibles = ~16 000 offres
actives, ~150 000 lignes historiques sur un an, charges utiles comprises autour
de 2 à 4 Go. SQLite tient ça sans transpirer — d'où ADR-002.

---

## 7. Invariants vérifiés en test

| # | Invariant |
|---|---|
| **I4** | Une seule offre `is_canonical=1` par `fingerprint` |
| **I5** | `tier='rejected'` ⟺ `rejection_reason IS NOT NULL` |
| **I7** | Toute ligne de `postings` a exactement une ligne de `raw_payloads` tant que la rétention ne l'a pas purgée |
| — | `user_flags` survit à un rejeu complet du pipeline sur les mêmes offres |
| — | Deux pages keyset consécutives ne se recouvrent ni ne sautent d'élément, tri par tri |
