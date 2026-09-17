# 08 — Tests

> Prérequis : [00-PRIMER.md](00-PRIMER.md).
> **À lire avant de coder quoi que ce soit.**

La propriété qui gouverne toute la stratégie de test : **le normaliseur et le
matcher se testent hors ligne, contre un corpus figé.** Aucune fixture réseau,
aucune base, aucun serveur LLM. C'est le contrat D8 de
[01-ARCHITECTURE.md](01-ARCHITECTURE.md) qui rend ça possible, et c'est pour ça
qu'il est non négociable.

---

## 1. Marqueurs pytest

```toml
markers = [
    "golden:   cascade complète contre le corpus doré (aucun réseau)",
    "contract: collecteurs contre charges utiles figées (aucun réseau)",
    "property: tests hypothesis (invariants I1→I3)",
    "db:       nécessite une base SQLite temporaire",
    "live:     appels réels aux sources externes — EXCLU de la CI",
]
addopts = "-m 'not live' --strict-markers"
```

`--strict-markers` : un marqueur mal orthographié échoue au lieu d'être ignoré.
Un test `live` qui tourne en CI est un test qui rendra la CI rouge le jour où
Greenhouse a un hoquet — on ne mélange pas les deux.

---

## 2. Le corpus doré

`tests/fixtures/postings/corpus.jsonl` — une offre **réelle** par ligne, avec
les champs attendus étiquetés à la main.

```json
{
  "id": "gh_optiver_4211",
  "source": "greenhouse",
  "title_raw": "Graduate Software Engineer (C++) — Amsterdam, 2026 Start",
  "description_raw": "…",
  "expect": {
    "role_family": "quant_dev",
    "seniority": "graduate",
    "min_years": null,
    "city": "Amsterdam", "country": "NL", "remote_mode": "onsite",
    "visa_sponsorship": "sponsors",
    "tech": ["cpp"],
    "closes_at": "2026-01-31T00:00:00Z"
  }
}
```

| Règle | Pourquoi |
|---|---|
| **Cible : 200 offres minimum**, réparties sur toutes les familles d'ATS et tous les continents | Un corpus mono-source teste un parseur de Greenhouse, pas un normaliseur |
| Une entrée est ajoutée **à chaque bug de parsing constaté**, avant le correctif | C'est ce qui transforme un bug en non-régression |
| `null` attendu est une assertion, pas une absence | « le champ n'est pas dit » est une information à ne pas perdre |
| Le corpus est **figé** : on ne le régénère pas, on l'étend | Un corpus régénérable ne détecte aucune régression |
| Les offres sont **anonymisées** de tout contact nominatif | On archive du texte d'annonce, pas des données personnelles |

`just test-golden` affiche le **taux de résolution par étage** :

```text
étage            résolus   cumul
title             198/200   99.0%
location          186/200   93.0%
seniority         171/200   85.5%
visa              142/200   71.0%
compensation       88/200   44.0%
```

Ce tableau est la mesure de progrès du projet. Il apparaît dans le rapport
hebdomadaire de WP16, et une baisse est un échec de build.

---

## 3. Tests de contrat des collecteurs

`tests/fixtures/payloads/<source>/<cas>.json` — des réponses réelles capturées
une fois, figées ensuite.

| Cas à couvrir, par source | Attendu |
|---|---|
| Réponse nominale | le bon nombre d'offres, champs mappés |
| Board vide | `CollectResult` avec 0 offre, **sans exception** |
| Board inexistant (404) | `BoardNotFound`, pas `SourceUnavailable` |
| Pagination multi-pages | toutes les pages consommées, `requests_made` juste |
| Budget de requêtes atteint | `truncated=True`, aucune exception |
| Champ manquant / null inattendu | offre ignorée avec log, run poursuivi |
| Charge utile qui ne ressemble plus à rien | `SourceSchemaChanged` |
| 429 | `SourceBlocked`, **pas** de retry immédiat |

**Capturer une charge utile est un acte explicite** : `tools/probe_ats.py
--save`. On ne fabrique pas de fausse charge utile à la main, sauf pour les cas
dégradés qu'on ne peut pas provoquer.

---

## 4. Invariants

| # | Invariant | Où | Comment |
|---|---|---|---|
| **I1** | Le normaliseur ne lève **jamais** d'exception sur une entrée arbitraire | `normalize` | `hypothesis` sur du texte quelconque |
| **I2** | `normalize` est **déterministe** : deux appels sur la même entrée donnent le même résultat, horloge figée | `normalize` | corpus × 2 |
| **I3** | Le préfiltre LLM a **zéro faux négatif** : toute offre écartée sans appel LLM aurait été rejetée par les règles de toute façon | `match.prefilter` | exhaustif sur le corpus + `hypothesis` |
| **I4** | Une seule offre canonique par empreinte | `store` | test `db` avec republications |
| **I5** | `tier='rejected'` ⟺ `rejection_reason` non nul | `match`, `store` | corpus + contrainte SQL |
| **I6** | Les facettes restent non nulles sur leur propre dimension sous filtre | `store.facets` | test `db` |
| **I7** | Toute offre a sa charge utile brute tant que la rétention ne l'a pas purgée | `store` | test `db` |

**I3 mérite d'être expliqué.** Le préfiltre existe pour ne pas payer de GPU sur
des offres évidemment hors sujet. S'il se trompe, il jette une offre sans que
rien ne le signale — un faux négatif invisible. On le construit donc de façon
**délibérément généreuse** : il n'écarte que ce dont il est certain, et
l'invariant le vérifie exhaustivement. Voir [wp/WP12-match-llm.md](wp/WP12-match-llm.md) §3.

---

## 5. Tests de la couche store

Base temporaire, migrations appliquées, marqueur `db`.

| Test | Attendu |
|---|---|
| Deux pages keyset consécutives, pour **chaque** tri | aucun recouvrement, aucun saut |
| Republication d'une offre déjà connue par une autre source | un alias, pas une offre |
| Offre ATS arrivant après un alias d'agrégateur | l'ATS devient canonique, **le favori suit** |
| Rejeu complet du pipeline | `user_flags` intacts |
| Filtre `visa={sponsors}` | n'inclut **pas** `unknown` |
| Filtre par défaut de l'API | inclut `unknown` (P4) |
| Purge de rétention | `raw_payloads` purgés, `postings` conservées, aucune cascade sauvage |

---

## 6. Tests du front

| Niveau | Outil | Portée |
|---|---|---|
| Unitaire | `vitest` | formatage des dates, devises, encodage/décodage de l'URL de filtres |
| Composant | RTL + **MSW** | le feed rend, filtre, pagine, sur des fixtures dérivées du schéma généré |
| Contrat | test de dérive | `schema.gen.ts` régénéré == commité, sinon échec |
| e2e | Playwright | parcours : charger, filtrer par pays, trier, mettre en favori, recharger l'URL et retrouver le même écran |
| Accessibilité | `axe` | zéro violation sérieuse sur le feed et le panneau de filtres |

Le **test de dérive** est celui qui protège vraiment : c'est lui qui rend
impossible le scénario où une route change côté Python et où le front continue à
compiler contre un type périmé.

---

## 7. CI

`.github/workflows/ci.yml`, trois jobs.

| Job | Contenu | Bloquant |
|---|---|---|
| `backend` | `ruff check` · `ruff format --check` · `mypy --strict` · `lint-imports` · `pytest -m "not live"` | ✅ |
| `frontend` | `tsc --noEmit` · `eslint` · `vitest run` · `npm run build` | ✅ |
| `api-contract` | `just types` puis `git diff --exit-code web/openapi.json web/src/api/schema.gen.ts` | ✅ |

`just ci` reproduit les trois localement. **Aucun job n'a accès au réseau vers
les sources** : tout ce qui est marqué `live` est exclu par construction.
