# WP20 — Les pistes : une seconde recherche, son propre score, son onglet

> **Contexte** : le mainteneur veut suivre, à côté du marché quant, les postes **C++, CUDA et
> machine learning situés en Suisse**, chez n'importe quel employeur — une banque zurichoise
> autant qu'une start-up de robotique lausannoise — dans le même front, sur un onglet à part.
> LinkedIn a été écarté pour cette recherche (risque sur le compte personnel) : elle passe par les
> ATS officiels, comme le reste.

**Dépend de** : WP05 (profil et score), WP02 (stockage), WP07 (API), WP10/WP11 (front).

---

## 1. Ce qu'est une piste

Une **piste** (`core.enums.Track`) est une recherche notée contre **son propre profil**, à côté du
flux quant. Elle ne collecte rien d'elle-même : la collecte, la normalisation, le dédoublonnage,
la relecture LLM restent **uniques**. Une offre est collectée une fois ; elle est notée contre le
profil quant (comme avant) **et** contre chaque piste dont elle est dans le périmètre.

Le flux quant n'est **pas** une piste : il reste le défaut, avec `verdicts` et le couple
`postings.score/tier` dénormalisé. Rien ne change pour lui, sinon la règle du §2.3.

| | Flux quant | Piste `ch_tech` |
|---|---|---|
| Profil | `configs/profile.yaml` | `configs/tracks.yaml` → `ch_tech`, **superposé** au profil quant |
| Périmètre | partout | un lieu en Suisse (`CH`) parmi ceux de l'offre, télétravail suisse compris |
| Sujet | la famille de rôle (`not_quant` si `other`) | un mot-clé du titre (C++, CUDA, GPU, ML…) **ou** un tag de stack (`cpp`, `cuda`, `pytorch`, `tensorflow`, `jax`) |
| Séniorité | junior (0-2 ans) | **la même**, héritée |
| Verdicts | `verdicts` + `postings.score/tier` | `track_verdicts` |
| Onglet | Feed (`/`) | Swiss tech (`/ch`) |

## 2. Le profil d'une piste

### 2.1 Superposition

Une entrée de `configs/tracks.yaml` est un **calque** sur `configs/profile.yaml`
(`match.profile.build_tracks`) : les mappings fusionnent clé par clé, une liste remplace celle du
quant en entier. Ce que la piste ne redit pas — voies LLM, règle de péremption, mots-clés de
séniorité, titres exclus — elle l'hérite. Le fichier montre donc **exactement** en quoi la piste
diffère. Chaque piste porte sa propre `version` : la changer fait renoter toute la piste.

### 2.2 Périmètre et sujet

- **Hors périmètre n'est pas un rejet.** Une offre parisienne n'a simplement **pas de ligne** dans
  `track_verdicts` pour `ch_tech` (`match.rules.in_scope`). Sinon l'onglet compterait en
  « rejetées » les 30 000 offres du reste du monde.
- **Hors sujet est un rejet**, motivé `off_topic` (jamais silencieux, principe du projet) : une
  offre suisse « Java Backend Developer » est dans le périmètre mais pas dans le sujet. Elle reste
  visible dans « Filtered out » de l'onglet, comme tout rejet.
- La correspondance des mots-clés du sujet se fait sur des **bords de mots** non alphanumériques,
  pas sur `\b` : « c++ » se termine par un caractère non-mot, où `\b` ne correspond jamais.

### 2.3 Le flux quant exclut les employeurs `tech`

Les sociétés ajoutées pour la piste ont le secteur **`tech`**. Leurs offres n'ont rien à faire dans
le flux quant, même quand leur titre y ressemble (« Software Engineer, C++ » chez Nvidia y ferait
un `possible`). `profile.yaml: scope.exclude_sectors: [tech]` les rejette en **`off_topic`** — et
non en `not_quant`, parce que la voie LLM (WP12) relit les `not_quant` des sociétés de rang 1 : ce
serait des centaines d'appels pour un rejet que le LLM ne peut pas renverser.

### 2.4 Ce qui est configurable, ce qui ne l'est pas

`niche_tech` (ce que récompense `tech_niche`) sort du code vers le profil : `kdb, ocaml, rust,
cuda, fpga` pour le quant (inchangé), la pile ML pour `ch_tech`. Les poids du visa sont faibles sur
la piste : le profil est ressortissant UE, le permis suisse est une formalité
([10-PROFILE-TARGET.md](../10-PROFILE-TARGET.md) §4).

## 3. Stockage et fraîcheur — `track_verdicts`

Migration `0010_track_verdicts.sql` : une ligne par `(track, posting_id)`, l'invariant I5 en
contrainte, et un index `(track, tier, score DESC, posting_id DESC)` pour le tri par défaut.

Le verdict d'une piste est **dérivé** : `runtime.tracks.score_tracks` le recalcule quand

1. la ligne manque (offre nouvelle, ou entrée dans le périmètre) ;
2. `profile_version` diffère (la piste a changé) ;
3. `verdicts.scored_at` est plus récent (le côté quant a renoté l'offre : contenu nouveau,
   correction du LLM, rejeu).

Et il supprime les lignes des offres sorties du périmètre (lieu corrigé, devenue alias) ou d'une
piste retirée de la configuration. La passe tourne après chaque cycle de source et après la
relecture LLM (`collect`, `loop`), et à la main : `just score-tracks`. Quand rien n'a changé, elle
coûte une requête par piste.

**Panne silencieuse** : une piste dont aucune offre n'est montrée après la passe lève
`track_empty` (avertissement), pas un silence.

La relecture LLM (WP19) lit « le meilleur score d'abord » : c'est désormais le meilleur du score
quant et des scores de piste, pour qu'un poste CUDA `strong` rejeté par le quant ne passe pas en
dernier.

## 4. Collecte — le registre `tech`

Les employeurs de la piste entrent dans `configs/companies.yaml` avec `sector: tech`, vérifiés par
`tools/probe_ats.py` comme tous les autres (jamais un jeton deviné). Les grands groupes publient
des milliers d'offres dans le monde : le collecteur Workday accepte `extra.facets`, le filtre natif
de la liste Workday (par exemple l'identifiant `locationCountry` de la Suisse chez ce locataire),
pour ne lister que le pays utile. Les boards Greenhouse / Ashby n'ont pas de filtre : ils sont
collectés en entier, et la piste ne retient que la Suisse.

Les entreprises sans ATS public (Google, Apple, Meta, Microsoft, IBM Research…) ne sont **pas**
couvertes : elles demanderaient une entrée `source: custom` chacune, à faire au cas par cas.

## 5. API et front

- `track` est un paramètre de requête de `/postings`, `/facets`, `/map/pins`,
  `/export/postings.csv` (via le filtre partagé `get_posting_filter`) et de `/postings/{id}` (le
  score, le palier et les raisons sont ceux de la piste quand elle a noté l'offre, ceux du quant
  sinon). Une piste inconnue est un 422.
- `store.postings.scoring_join` ajoute la jointure sur `track_verdicts` ; score, palier et motif de
  rejet y sont lus à la place des colonnes de `postings`. Le flux quant garde sa requête et son
  index.
- Front : onglet **Swiss tech** sur `/ch` (détail en `/ch/p/{id}`). C'est le même `FeedScreen`,
  avec `track="ch_tech"` : la piste appartient à **l'écran**, pas à l'URL — elle accompagne chaque
  requête mais n'entre ni dans la chaîne de requête, ni dans les pastilles, ni dans une vue
  sauvegardée. Le cache du détail est clé `['posting', id, track]` ; ce qui modifie l'offre elle-même
  (favori, tri, note) met à jour toutes ses copies par le préfixe `['posting', id]`.

## 6. Ajouter une piste

1. une valeur dans `core.enums.Track` (+ `tests/fixtures/enum_snapshot.json`) ;
2. son calque dans `configs/tracks.yaml` ;
3. un onglet : une route dans `web/src/app/routes.ts`, un lien dans `top-nav.tsx`, un
   `<FeedScreen track=… basePath=…>` dans `App.tsx` ;
4. `just types`, puis `just score-tracks`.

## 7. Mise en route sur une base existante

```sh
just migrate                                        # 0010_track_verdicts
just replay --normalize-version-below 9 --apply     # tags pytorch / tensorflow / jax (NORMALIZE_VERSION 9)
just collect                                        # les nouvelles sociétés `tech`, puis la passe des pistes
```
