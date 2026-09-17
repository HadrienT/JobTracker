# WP02 — `store` : persistance, facettes, recherche

> **Contexte** : la couche que l'API et le pipeline partagent. Elle porte deux
> responsabilités qu'on sous-estime toujours — la **pagination keyset** et les
> **facettes sous filtre** — et elles sont toutes deux plus subtiles qu'elles
> n'en ont l'air.
>
> Le bug que ce lot doit rendre impossible : scroller trois écrans et revoir une
> offre déjà vue, ou en sauter une. Ça vient d'un tri sans départageur, ça ne se
> voit jamais en test manuel, et ça décrédibilise l'outil entier.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[04-DATA-MODEL.md](../04-DATA-MODEL.md) · [03-INTERFACES.md](../03-INTERFACES.md) §3.5 ·
[08-TESTING.md](../08-TESTING.md) §5

**Dépend de** : WP01. **Parallélisable avec** : WP03 · WP09.

---

## 1. Objectif

Le schéma de [04-DATA-MODEL.md](../04-DATA-MODEL.md), ses migrations, et les
huit modules de dépôt. Y compris `PostingFilter` — **le contrat de filtrage
partagé avec l'API**.

---

## 2. Pagination keyset

Le curseur encode `(valeur de la clé de tri, posting_id)`, sérialisé en base64
opaque. Le client ne le lit jamais.

```sql
-- tri par score décroissant, page suivante
WHERE (score, posting_id) < (:cursor_score, :cursor_id)
ORDER BY score DESC, posting_id DESC
LIMIT :limit
```

| Règle | Raison |
|---|---|
| **Tout tri inclut `posting_id` en second critère** | Deux offres à 87 points rendent sinon le curseur ambigu : on saute ou on répète |
| Le curseur est **opaque** | On doit pouvoir changer d'implémentation sans casser les clients |
| Un curseur invalide → **400**, pas une première page silencieuse | Sinon un scroll infini boucle sans que personne ne comprenne |
| Les tris sur colonne `NULL`able (`posted_at`, `closes_at`) fixent explicitement `NULLS LAST` | SQLite trie les `NULL` en premier par défaut, ce qui met les offres sans date en tête du tri « plus récentes » |

Ce dernier point est un piège réel : trier par `closes_at` sans `NULLS LAST`
remonte en tête toutes les offres **sans** date de clôture, c'est-à-dire
exactement l'inverse de ce qu'on demande.

---

## 3. Facettes — l'invariant I6

`facet_counts(conn, flt)` renvoie les comptes **sous le filtre courant, sauf sur
la dimension comptée**.

```text
filtre : country ∈ {GB, US}, tech ∋ cpp

facette pays   → comptée avec tech ∋ cpp,    SANS le filtre pays
                 → FR: 34, NL: 51, CH: 12, GB: 210, US: 180
facette stack  → comptée avec country ∈ {GB,US}, SANS le filtre stack
                 → cpp: 390, python: 512, rust: 40
```

Sans cette exclusion, cocher `GB` fait tomber toutes les autres lignes du filtre
pays à zéro, et on ne peut plus ajouter `US` sans tout réinitialiser. C'est
l'invariant **I6**, et c'est la différence entre un panneau de filtres utilisable
et un cul-de-sac.

Implémentation : une requête par dimension, chacune avec son propre filtre
amputé. Sept petites requêtes indexées battent une grosse requête d'agrégation
croisée, et elles se testent une par une.

---

## 4. Upsert et dédoublonnage

`upsert_posting` applique la résolution d'empreinte de
[03-INTERFACES.md](../03-INTERFACES.md) §3.4. Les trois branches :

| Cas | Action |
|---|---|
| Empreinte inconnue | Nouvelle offre canonique |
| Empreinte connue, existant = ATS, nouveau = agrégateur | `record_alias`, **aucune offre créée** |
| Empreinte connue, existant = agrégateur, nouveau = ATS | **Bascule** : l'ATS devient canonique, l'ancien devient alias, et **`user_flags` suit l'identifiant canonique** |

La bascule est le cas délicat : un favori posé sur la version LinkedIn d'une
offre doit se retrouver sur la version Greenhouse quand elle arrive. Sinon
l'utilisateur perd ses favoris sans comprendre pourquoi.

`content_hash` inchangé → on met à jour `last_seen_at` et **on ne rescore pas**.
C'est ce qui évite de repasser 16 000 offres au scoring à chaque cycle.

---

## 5. FTS5

Table externe (`content=''`), synchronisée par triggers, tokenizer
`unicode61 remove_diacritics 2`.

`remove_diacritics 2` n'est pas un détail : le flux contient des annonces
françaises, allemandes et néerlandaises, et « Développeur » doit se trouver en
tapant « developpeur ».

La description complète vit **dans FTS et pas dans `postings`** : la colonne
serait lourde, jamais lue par le flux, et relue seulement dans le détail.

---

## 6. Tests attendus

| Test | Attendu |
|---|---|
| Deux pages keyset consécutives, **pour chaque tri** | aucun recouvrement, aucun saut |
| Insertion pendant la pagination | aucune ligne dupliquée dans les pages déjà servies |
| Égalité de score sur 200 lignes | ordre stable, départagé par `posting_id` |
| Tri par `closes_at` | offres sans clôture **en dernier** |
| Curseur corrompu | erreur explicite, pas un retour à la page 1 |
| Facettes sous filtre | invariant **I6** vérifié dimension par dimension |
| Republication par un agrégateur | un alias, **pas** une offre |
| ATS arrivant après un alias | bascule canonique, **favori conservé** |
| Rejeu complet du pipeline | `user_flags` intacts |
| `content_hash` inchangé | `last_seen_at` mis à jour, `scored_at` inchangé |
| Purge de rétention | `raw_payloads` purgés, `postings` conservées |
| FTS « developpeur » | trouve « Développeur » |
| Migration appliquée deux fois | idempotente |

---

## 7. Critères d'acceptation

- [ ] `migrations/0001_initial.sql` crée le schéma complet de [04-DATA-MODEL.md](../04-DATA-MODEL.md).
- [ ] Les invariants **I4**, **I5**, **I6**, **I7** sont couverts par des tests.
- [ ] La pagination keyset est testée sur **les cinq tris**, avec insertion concurrente.
- [ ] `PostingFilter` est défini une seule fois et importé par l'API (WP07).
- [ ] Aucun `OFFSET` dans le code (ADR-007) — vérifiable par `grep`.
- [ ] Les montants transitent en `Decimal` de bout en bout, `TEXT` en base.
- [ ] `lint-imports` : contrat **D2** vert.
- [ ] `mypy --strict` passe.
