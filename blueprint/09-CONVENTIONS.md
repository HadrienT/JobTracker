# 09 — Conventions de code

> Prérequis : [00-PRIMER.md](00-PRIMER.md).
> **À lire avant de coder quoi que ce soit.**

---

## 1. Outillage

| Rôle | Outil | Configuration |
|---|---|---|
| Environnement & dépendances | `uv` | `pyproject.toml` |
| Lint & format | `ruff` | ligne 100 |
| Typage | `mypy --strict` | tout `src/` |
| Tests | `pytest` + `hypothesis` | marqueurs de [08-TESTING.md](08-TESTING.md) |
| Règles d'architecture | `import-linter` | contrats D1→D9 de [01-ARCHITECTURE.md](01-ARCHITECTURE.md) |
| Migrations | SQL brut versionné | `migrations/` |
| Tâches | `just` | `justfile` |
| Front | `eslint` **bloquant** + `tsc --noEmit` | `web/` |

Python **3.13** partout — poste, serveur, CI. Node 20 pour le front.

---

## 2. Langue

| Élément | Langue |
|---|---|
| Conversation avec le mainteneur | **français** |
| `blueprint/`, `docs/` | **français** |
| Code, identifiants, commentaires, docstrings | anglais |
| Messages de commit, issues, PR | anglais |
| **Interface du front** | anglais |

Le front est en anglais parce que le contenu qu'il affiche l'est : mélanger
« Filtrer par pays » et « Senior Quantitative Developer, London » dans le même
écran est plus laid qu'utile.

---

## 3. Unités, types et grandeurs

**Cause n°1 de bug silencieux dans ce projet.** Une confusion ne plante pas :
elle produit une offre plausible et fausse, ou elle en fait disparaître une
bonne.

| Grandeur | Type | Nom de paramètre |
|---|---|---|
| Argent | `Decimal` | `salary_min`, `salary_max` — **toujours** avec `currency` et `period` |
| Durée | `int` avec suffixe | `timeout_s`, `interval_min`, `duration_ms`, `window_days` |
| Horodatage | `datetime` **aware UTC** | `posted_at`, `first_seen_at`, `closes_at` |
| Score | `int` 0→100 | `score` |
| Années d'expérience | `int | None` | `min_years` — **`None` ≠ `0`** |
| Pays | `str` ISO-3166 alpha-2 majuscule | `country` |
| Devise | `str` ISO-4217 majuscule | `currency` |
| Langue | `str` ISO-639-1 minuscule | `languages_required` |

| # | Règle |
|---|---|
| **N1** | Tout paramètre porte son unité en suffixe : `_s`, `_min`, `_ms`, `_days`, `_h`. |
| **N2** | L'argent est en `Decimal`. Aucun `float` ne touche un montant, de la lecture de l'API à l'écriture en base. |
| **N3** | **Aucune conversion de devise en base.** On stocke `(montant, devise, période)`. La conversion est un affichage, avec un taux daté. |
| **N4** | `None` signifie « non dit », jamais « zéro ». Vrai pour `min_years`, `salary_*`, `posted_at`, `closes_at`. |
| **N5** | `VisaStatus.UNKNOWN` n'est **ni** `SPONSORS` **ni** `NO`. Trois branches, partout, y compris dans l'UI. |
| **N6** | Aucun `datetime.now()`. `core.clock.utc_now()` uniquement, pour que les tests figent l'horloge. |
| **N7** | Aucune date naïve. Tout `datetime` porte son fuseau, et ce fuseau est UTC. |

### La règle des dates de publication

Les sources mentent sur `posted_at`, ou l'omettent, ou remontent la date
d'indexation de leur propre agrégateur. Le champ **fiable** est `first_seen_at` :
c'est nous qui l'écrivons.

```text
âge affiché = posted_at s'il existe ET s'il est antérieur à first_seen_at
              sinon first_seen_at
```

Un `posted_at` **postérieur** à `first_seen_at` est absurde : il signifie que la
source a réécrit la date pour faire paraître l'offre fraîche. On l'ignore, et on
le journalise. Le tri « plus récentes » utilise cette formule, jamais `posted_at`
brut.

---

## 4. Nommage

| Élément | Convention | Exemple |
|---|---|---|
| Package | `snake_case`, court, un nom de responsabilité | `collect`, `normalize`, `match`, `store` |
| Module | `snake_case`, nom = responsabilité | `location.py`, `prefilter.py`, `watchdog.py` |
| Classe | `PascalCase` | `Breaker`, `CollectResult` |
| Protocol | `PascalCase`, **sans** suffixe `Interface`/`ABC` | `Collector`, `HttpSession` |
| DTO pydantic | `PascalCase` + suffixe de rôle | `RawPosting`, `Posting`, `MatchVerdict` |
| Fonction | `snake_case`, verbe | `parse_location`, `list_postings` |
| Constante | `UPPER_SNAKE` | `DEFAULT_LIMIT` |
| Table SQL | `snake_case` pluriel | `postings`, `source_runs` |
| Migration | `NNNN_description.sql` | `0003_posting_aliases.sql` |
| Motif de rejet | `snake_case`, stable, **jamais traduit** | `senior_only`, `phd_required`, `not_quant` |
| Composant React | `PascalCase`, un fichier | `PostingRow.tsx` |
| Hook | `useXxx` | `usePostings` |

**Interdits de nommage** : `utils.py`, `helpers.py`, `misc.py`, `common.py`,
`manager.py`, `service.py`, ainsi que `data`, `tmp`, `obj`, `mgr`, `do_stuff`.

Les motifs de rejet, les codes de `Reason`, les valeurs de `StrEnum` et les
`company_slug` sont des **identifiants** : ils sont en base, dans les URL
partagées, comparés en test, et utilisés pour cibler un rejeu. Les renommer casse
l'historique et les liens sauvegardés.

---

## 5. Typage

- `mypy --strict`. Aucun `# type: ignore` sans commentaire justificatif **sur la
  même ligne**.
- Aucun `Any` dans une signature publique. Les charges utiles de sources arrivent
  en `Any` et sont validées **immédiatement** en DTO à la frontière du collecteur.
- Les DTO sont `frozen=True`. Un étage retourne un nouvel objet, il ne mute pas
  son entrée — c'est ce qui rend chaque étage testable isolément et rejouable.
- Les énumérations sont des `StrEnum`.
- Côté front : `strict: true`, `noUncheckedIndexedAccess: true`, et **aucun
  `any`**. Les types de réponse viennent de `schema.gen.ts`, jamais d'une
  interface écrite à la main (ADR-005).

---

## 6. Style

- Docstring d'une ligne sur les fonctions publiques uniquement. Le code dit
  *comment*, le blueprint dit *pourquoi*.
- Un commentaire explique une **décision non évidente**, jamais ce que fait la
  ligne. Si un commentaire paraphrase le code, il est faux dans six mois.
- Fonctions courtes, un niveau d'abstraction par fonction.
- Aucune valeur littérale de seuil, de poids ou de cadence dans le code : elle
  vient de `configs/` ([06-CONFIG.md](06-CONFIG.md) règle C1).
- Les regex d'extraction vivent dans `configs/taxonomy.yaml` quand elles
  expriment un choix métier, dans le module quand elles expriment une grammaire.
  En cas de doute : configuration.

---

## 7. Git

- **Une branche par lot de travail**, jamais de commit direct sur `main`.
  Nom de branche : `wp03-normalize`, `wp10-web-feed`.
- Messages de commit en anglais, impératif, terminés par
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- Un commit qui change une route ou un schéma d'API **contient** les fichiers
  générés par `just types`.
- Un commit qui ajoute un paramètre **contient** la mise à jour de
  `.env.example` et de [06-CONFIG.md](06-CONFIG.md).

---

## 8. Definition of Done

- [ ] `mypy --strict` passe.
- [ ] `ruff check` et `ruff format --check` passent.
- [ ] `lint-imports` passe (D1→D9).
- [ ] Tests unitaires ; pour `normalize` et `match`, non-régression sur le corpus doré.
- [ ] Les invariants de [08-TESTING.md](08-TESTING.md) §4 concernés sont couverts.
- [ ] Aucun seuil, poids ou cadence en dur.
- [ ] Erreurs issues de la taxonomie de [07-ERRORS-AND-LOGGING.md](07-ERRORS-AND-LOGGING.md).
- [ ] Journalisation structurée aux frontières, avec `run_id`.
- [ ] Aucun secret dans le code ni dans les logs.
- [ ] `.env.example` et [06-CONFIG.md](06-CONFIG.md) à jour.
- [ ] Front : `tsc --noEmit` et `eslint` passent, `schema.gen.ts` régénéré si besoin.
- [ ] Points d'API tierce incertains marqués `[À CONFIRMER]`, jamais devinés.
