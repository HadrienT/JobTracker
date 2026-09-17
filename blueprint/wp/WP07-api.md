# WP07 — `api` : FastAPI en lecture

> **Contexte** : la frontière entre le backend et le front. Elle est volontairement
> mince — l'API ne contient **aucune logique métier**, elle traduit des paramètres
> de requête en `PostingFilter` et appelle `store`.
>
> Le lot peut démarrer **avant** que WP02 ne soit fini : la forme de l'OpenAPI ne
> dépend pas du SQL. Avec une implémentation bouchon de `list_postings`, l'API est
> écrite, son schéma est généré, et WP10 peut commencer à consommer de vrais types.
> C'est le déblocage le plus rentable du plan de parallélisation.

**Fichiers à lire** : ce fichier · [03-INTERFACES.md](../03-INTERFACES.md) §3.5-3.6 ·
[04-DATA-MODEL.md](../04-DATA-MODEL.md) · [07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md) §5 ·
[12-WEB-UI.md](../12-WEB-UI.md) §4-5

**Dépend de** : WP02 (contrat suffit pour démarrer). **Parallélisable avec** : WP05 · WP06.

---

## 1. Objectif

Les sept routes de [03-INTERFACES.md](../03-INTERFACES.md) §3.6, le schéma
OpenAPI généré et commité, et la tâche `just types`.

---

## 2. Principes

| Règle | Raison |
|---|---|
| Une route se lit en **dix lignes** | Le SQL est dans `store`, testé sans serveur |
| Les schémas de réponse sont **distincts** des DTO internes | Ils font partie du contrat public ; un renommage interne ne doit pas casser le front |
| `limit` plafonné à **100** côté serveur | Un client ne dicte pas la charge |
| Tableaux en **paramètres répétés** (`?countries=GB&countries=US`) | C'est ce que FastAPI génère et ce que le générateur TypeScript comprend |
| Curseur invalide → **400** | Jamais un retour silencieux à la page 1 |
| Aucune authentification | Outil mono-utilisateur derrière un tunnel privé (ADR-011) |

---

## 3. `GET /postings`

Tous les champs de `PostingFilter` en paramètres de requête, plus `sort`,
`cursor`, `limit`.

**Les valeurs par défaut sont une décision produit, pas un détail technique :**

| Paramètre | Défaut | Pourquoi |
|---|---|---|
| `visa` | `{sponsors, unknown}` | P4 : on n'exclut que les `no` explicites. Un défaut qui écarte `unknown` ferait disparaître la majorité du flux sans le dire |
| `tiers` | `{strong, possible, stretch}` | Les rejetées sont accessibles, mais pas dans le flux par défaut |
| `sort` | `score` | |
| `posted_within_days` | aucun | Le filtre `stale` de WP05 fait déjà le ménage |
| `include_hidden` | `false` | |
| `limit` | `50` | |

Un défaut qui cache silencieusement des offres est le pire réglage possible pour
cet outil : on ne peut pas remarquer l'absence de ce qu'on n'a jamais vu.

---

## 4. `GET /facets`

Mêmes filtres, renvoie les comptes par dimension. Appelé **en parallèle** de
`/postings` par le front : une facette lente dégrade le panneau de filtres,
jamais le flux.

Respecte l'invariant **I6** : les comptes d'une dimension sont calculés **sans**
le filtre de cette dimension ([WP02](WP02-store.md) §3).

---

## 5. `GET /health`

Forme en [07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md) §5.

**Renvoie 200 même en état dégradé** : c'est une page d'état, pas une sonde de
liveness. Le front en fait un bandeau — un flux périmé doit être visible pendant
qu'on scrolle, sinon on lit des offres mortes en croyant que le marché est calme.

---

## 6. Écritures

Deux routes, `POST /postings/{id}/favorite` et `/hide`. Elles écrivent
`user_flags`, en **transactions d'une seule instruction**.

C'est le seul point où l'API écrit, et il est conçu pour ne jamais entrer en
conflit avec le pipeline de collecte : `user_flags` est une table séparée
([04-DATA-MODEL.md](../04-DATA-MODEL.md) §2), donc une passe de normalisation ne
peut pas écraser un favori.

---

## 7. `just types`

```sh
python tools/gen_openapi.py web/openapi.json
cd web && npm run api:types:local
```

Les deux fichiers sont **commités**. Le job CI `api-contract` régénère et échoue
si le diff n'est pas vide (ADR-005).

`gen_openapi.py` doit tourner **sans base** et **sans serveur** : il importe
l'application et sérialise son schéma. Un générateur qui exige une base qui
tourne ne sera pas lancé en CI, donc la dérive reviendra.

---

## 8. Tests attendus

| Test | Attendu |
|---|---|
| Chaque filtre pris isolément | restreint réellement le résultat |
| **Tous** les filtres combinés | aucune erreur SQL, résultat cohérent |
| Filtre absent de l'URL | défaut du §3 appliqué, et **documenté dans l'OpenAPI** |
| `visa` non précisé | `unknown` **inclus** |
| `limit=5000` | plafonné à 100, pas d'erreur |
| Curseur corrompu | 400 avec un message clair |
| Pagination complète d'un jeu de 500 offres | 10 pages, aucun doublon, aucun saut |
| `/facets` sous filtre | invariant **I6** |
| `/postings` et `/facets` avec les mêmes filtres | comptes cohérents |
| Favori posé puis pipeline rejoué | favori conservé |
| `/health` en état dégradé | **200**, avec les alertes listées |
| Schéma OpenAPI | régénéré == commité |

---

## 9. Critères d'acceptation

- [ ] Les sept routes existent et correspondent à [03-INTERFACES.md](../03-INTERFACES.md) §3.6.
- [ ] `PostingFilter` est **importé** de `store`, pas redéfini.
- [ ] Les défauts du §3 sont appliqués **et visibles dans l'OpenAPI**.
- [ ] `limit` plafonné à 100.
- [ ] Aucune requête SQL dans `api/` — tout passe par `store`.
- [ ] `just types` tourne sans base ni serveur, et les fichiers générés sont commités.
- [ ] Le job CI `api-contract` est en place et bloquant.
- [ ] `lint-imports` : contrat **D6** vert.
- [ ] `mypy --strict` passe.
