# 01 — Architecture

> Prérequis : [00-PRIMER.md](00-PRIMER.md).
> À lire si vous touchez à plus d'un package.

---

## 1. Les sept packages

```text
src/jobtracker/
├── core/        # socle partagé — ne dépend de rien
├── store/       # persistance et lecture — dépend de core
├── collect/     # réseau vers les sources — dépend de core
├── normalize/   # RawPosting → Posting — dépend de core, ZÉRO I/O
├── match/       # Posting → MatchVerdict — dépend de core, ZÉRO I/O sauf match.llm
├── api/         # FastAPI en lecture — dépend de core + store
└── runtime/     # composition, ordonnancement, CLI — dépend de tout
```

| Package | Responsabilité | Ne fait **jamais** |
|---|---|---|
| `core` | Configuration, journalisation, taxonomie d'erreurs, connexion SQLite, DTO pydantic, horloge, hachage, monnaie, référentiel géographique | Importer un autre package `jobtracker` |
| `store` | Migrations, dépôts par agrégat, requêtes de facettes, index FTS5, rétention | Parler réseau · contenir de la logique métier |
| `collect` | Un collecteur par **famille de source**, politique HTTP commune (cadence, gigue, repli, archivage brut) | Interpréter le contenu d'une offre · écrire en base |
| `normalize` | Cascade déterministe : lieu, séniorité, stack, rémunération, visa, empreinte | La moindre I/O — réseau, disque ou base |
| `match` | Grille de scoring déterministe ; `match.llm` pour le résidu ambigu | Toute I/O hors `match.llm` · écrire en base |
| `api` | Lecture : filtres, tri, facettes, pagination keyset. Écriture minuscule : favori, masquage | Collecter · normaliser · scorer |
| `runtime` | Composition racine : ordonnanceur, disjoncteur, chien de garde, CLI, rapports de run | Contenir de la logique métier réutilisable |

**Pourquoi `collect` n'écrit pas en base.** Un collecteur rend une séquence
d'offres brutes ; c'est `runtime` qui persiste. Conséquence directe : un
collecteur se teste contre des charges utiles figées, sans base, sans réseau,
sans fixture SQLite. C'est ce qui rend les tests de contrat de
[08-TESTING.md](08-TESTING.md) §3 possibles.

**Pourquoi `normalize` et `match` sont interdits d'I/O.** Le normaliseur est le
seul composant qu'on améliorera indéfiniment. On l'améliore en le **rejouant sur
l'archive brute** (WP16) et en mesurant. Un normaliseur qui fait un appel réseau
n'est pas rejouable, donc pas mesurable, donc il n'est plus améliorable.

---

## 2. Contrats d'import — vérifiés par `import-linter`

Les contrats sont dans `pyproject.toml`, section `[tool.importlinter]`, et
`just arch` les vérifie. Ils échouent le build en CI.

| # | Contrat | Nature |
|---|---|---|
| **D1** | `core` n'importe aucun autre package `jobtracker` | `forbidden` |
| **D2** | `store` n'importe que `core` | `forbidden` |
| **D3** | `normalize` n'importe que `core` | `forbidden` |
| **D4** | `match` n'importe que `core` (et `normalize` pour ses types de sortie) | `forbidden` |
| **D5** | `collect` n'importe que `core` | `forbidden` |
| **D6** | `api` n'importe que `core` et `store` | `forbidden` |
| **D7** | Aucun package n'importe `runtime` | `forbidden` |
| **D8** | Aucun client HTTP (`httpx`, `curl_cffi`, `requests`, `urllib`) importé hors `collect` et `match.llm` | `forbidden` (modules externes) |
| **D9** | Couches : `runtime` → `api` → {`match`, `normalize`, `collect`, `store`} → `core` | `layers` |

**D8 est le contrat qui compte.** C'est lui qui garantit que le corpus doré
reste exécutable hors ligne. `match.llm` en est l'**unique exception
documentée** : c'est le seul module de `normalize`/`match` autorisé à ouvrir une
socket, et il est isolé dans son propre fichier pour que cette exception soit
visible dans le diff.

---

## 3. Topologie runtime

Deux processus, un fichier.

```text
┌──────────────────────────────┐        ┌───────────────────────────┐
│ jobtracker loop              │        │ uvicorn jobtracker.api    │
│ (ordonnanceur de collecte)   │        │ (lecture)                 │
│                              │        │                           │
│  collect → normalize → match │        │  /postings  /facets       │
│         ↓                    │        │  /companies /health       │
└─────────┬────────────────────┘        └───────────┬───────────────┘
          │ écriture                                │ lecture (+ favoris)
          ▼                                         ▼
     ┌────────────────────────────────────────────────────┐
     │   jobtracker.db   —   SQLite, journal WAL          │
     │   + jobtracker.db-wal, jobtracker.db-shm           │
     └────────────────────────────────────────────────────┘
                              ▲
                              │ HTTP local, concurrence 1
                   ┌──────────┴───────────┐
                   │ llama-server :8000   │  partagé avec OpenHands
                   └──────────────────────┘
```

**Règles de concurrence SQLite**, à respecter à la lettre (ADR-002) :

- Journal **WAL**, `busy_timeout` à 5 000 ms, `foreign_keys=ON`,
  `synchronous=NORMAL`. Réglé une seule fois, dans `core.db`, jamais ailleurs.
- **Un seul écrivain** : le processus de collecte. L'API n'écrit que les favoris
  et les masquages, en transactions d'une instruction.
- Aucune transaction longue. Une collecte écrit par lots de source, pas en une
  transaction de dix minutes — sinon l'API prend des `SQLITE_BUSY` sur ses
  écritures de favoris.
- Le fichier de base n'est **jamais** sur un montage réseau.

---

## 4. Flux de données

```text
     configs/companies.yaml
             │  (registre : société → source + jeton)
             ▼
        ┌─────────┐   RawPosting[]    ┌──────────┐
        │ collect │ ────────────────▶ │ runtime  │
        └─────────┘   + payload brut  └────┬─────┘
             ▲                             │ archive brute (zstd)
             │ HTTP                        ▼
     ┌───────┴────────┐              ┌──────────┐
     │ ATS & sites    │              │  store   │
     └────────────────┘              └────┬─────┘
                                          │ RawPosting
                                          ▼
                                    ┌───────────┐  Posting   ┌────────┐
                                    │ normalize │ ─────────▶ │ match  │
                                    └───────────┘            └───┬────┘
                                                                 │ MatchVerdict
                                                                 ▼
                                                            ┌────────┐
                                                            │ store  │
                                                            └───┬────┘
                                                                │
                                                                ▼
                                                         api → web/
```

Chaque flèche est un **DTO `frozen`** décrit en [03-INTERFACES.md](03-INTERFACES.md).
Aucun étage ne mute son entrée ; il en produit une nouvelle. C'est ce qui permet
de tester chaque étage isolément et de rejouer les étages aval sur l'archive.

---

## 5. Où vit quoi — les erreurs de placement fréquentes

| Tentation | Où ça doit aller | Pourquoi |
|---|---|---|
| « Je parse la ville dans le collecteur Greenhouse, c'est plus simple » | `normalize.location` | Sinon chaque collecteur réinvente le parsing et aucun n'est testé contre le corpus |
| « Je filtre les offres senior directement à la collecte, ça économise du stockage » | `match` | Le stockage ne coûte rien ; un filtre non rejouable coûte cher. On archive tout, on filtre en aval |
| « Je mets la requête de facettes dans la route FastAPI » | `store.facets` | La route doit être lisible en dix lignes ; le SQL se teste sans serveur |
| « Je mets le décodage des salaires dans `core.money` » | `normalize.compensation` | `core` porte les types et la conversion, pas l'extraction depuis du texte libre |
| « Je mets la logique de retry dans chaque collecteur » | `collect.http` | Politique unique, testée une fois, respectée par construction |
| « Je mets le registre d'entreprises en base » | `configs/companies.yaml` | C'est du code source : versionné, relu en diff, pas une donnée mutable |

---

## 6. Front — frontière avec le backend

Le front ne connaît le backend que par **le contrat OpenAPI**. Il n'y a pas
d'autre couplage :

- `web/openapi.json` et `web/src/api/schema.gen.ts` sont **générés** par
  `just types` et **commités**.
- Le job CI `api-contract` régénère et échoue si le diff n'est pas vide. Une
  route ajoutée sans régénération casse la CI, pas la production.
- Le front n'écrit **aucun** type de réponse à la main (ADR-005).
- En développement, le front peut tourner seul contre **MSW** avec des fixtures
  dérivées du même schéma — c'est ce qui rend WP09 démarrable à la minute zéro,
  avant que l'API n'existe.
