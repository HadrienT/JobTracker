# WP11 — Front : filtres, facettes, URL partageable

> **Contexte** : le lot qui rend le flux **exploitable**. Un flux mondial de 15 000
> offres sans filtres n'est pas un outil, c'est un mur.
>
> Deux décisions gouvernent tout ce lot, et elles sont déjà prises : l'état des
> filtres vit **dans l'URL** (ADR-008), et le filtre visa par défaut **n'exclut
> pas `unknown`** (P4). La seconde est la plus facile à trahir par inadvertance —
> un développeur qui « nettoie » les valeurs par défaut pour avoir un flux plus
> propre supprime silencieusement la majorité des offres recevables.

**Fichiers à lire** : ce fichier · [12-WEB-UI.md](../12-WEB-UI.md) §4-5 ·
[00-PRIMER.md](../00-PRIMER.md) §2 (P4) · [decisions.md](../decisions.md) ADR-008 ·
[03-INTERFACES.md](../03-INTERFACES.md) §3.5

**Dépend de** : WP10. **Parallélisable avec** : WP12 · WP13.

---

## 1. Objectif

Le panneau de filtres à facettes, l'encodage complet de l'état dans l'URL, les
favoris, et les écrans `companies` et `health`.

---

## 2. L'URL est la source de vérité

```text
/?countries=GB&countries=US&tech_all=cpp&seniorities=graduate&visa=sponsors&visa=unknown&sort=score
```

| Règle | Conséquence |
|---|---|
| Tout l'état de filtre, de tri et de recherche est encodé dans l'URL | L'écran est partageable et rechargeable |
| Aucun store global pour les filtres | Pas de synchronisation à maintenir entre deux sources de vérité |
| Le décodage est **tolérant** : un paramètre inconnu est ignoré, une valeur invalide retombe sur le défaut | Une URL d'une version antérieure ne casse pas la page |
| Le décodeur et l'encodeur sont testés en **aller-retour** | C'est la seule garantie que le bouton Précédent fonctionne |

Bénéfice secondaire mais réel : un bug de filtre se rapporte en collant une URL
dans l'issue. Avec un store en mémoire, il se rapporte en décrivant une séquence
de clics.

---

## 3. Le panneau

Les treize dimensions de [12-WEB-UI.md](../12-WEB-UI.md) §4, chacune avec son
compte issu de `/facets`.

| Comportement | Règle |
|---|---|
| Comptes | Sous le filtre courant, **sauf sur la dimension comptée** (invariant I6) |
| Dimension à zéro | Affichée grisée, **pas masquée** — un filtre qui disparaît est un filtre qu'on ne peut pas décocher |
| Stack | Bascule explicite « toutes » / « au moins une » (`tech_all` / `tech_any`) |
| Recherche | Débattue à 250 ms, envoyée en FTS5 |
| Réinitialiser | Un bouton unique qui revient aux **défauts**, pas à vide |
| Filtres actifs | Résumés en pastilles au-dessus du flux, chacune supprimable d'un clic |

**Le filtre visa** a trois cases : `sponsors`, `unknown`, `no`. Les deux
premières sont cochées par défaut. Un libellé explicite — « visa not mentioned »
plutôt que « unknown » — parce que c'est le cas majoritaire et qu'il ne doit pas
ressembler à une donnée manquante.

---

## 4. Favoris et masquage

| Action | Comportement |
|---|---|
| Favori | Mise à jour **optimiste**, rollback + toast en cas d'échec |
| Masquage | Idem, plus un retrait animé de la liste avec annulation possible |
| Vue favoris | Un filtre de plus (`favorites_only`), donc dans l'URL, donc partageable |

Les favoris survivent à tout : à un rejeu du pipeline, à une bascule de source
canonique ([WP02](WP02-store.md) §4), à la disparition de l'offre du board.

---

## 5. Écrans `companies` et `health`

| Écran | Contenu | À quoi il sert vraiment |
|---|---|---|
| `/companies` | Registre : offres actives, dernière collecte réussie, statut | **Repérer une société muette.** Une société à 0 offre depuis trois semaines est probablement un jeton cassé, pas un gel des embauches |
| `/health` | Rendu de `GET /health` | Voir les sources dégradées. Un **bandeau** apparaît sur le feed quand le flux est périmé |

Le bandeau de flux périmé est la traduction de P3 dans l'interface : si la
collecte est cassée, l'utilisateur doit le voir **pendant qu'il scrolle**, pas
en allant chercher une page d'état.

---

## 6. Tests attendus

| Test | Attendu |
|---|---|
| Aller-retour URL ↔ état, sur les treize dimensions | identité |
| URL avec paramètre inconnu | ignoré, page rendue |
| URL avec valeur invalide | retombe sur le défaut, aucune erreur |
| URL sans paramètre `visa` | `sponsors` **et** `unknown` cochés |
| Recharger une URL de filtres | même écran, même tri |
| Bouton Précédent après trois filtres | revient au filtre précédent |
| Cocher un pays | les autres pays **restent** sélectionnables avec leurs comptes (I6) |
| Dimension à zéro | grisée, pas masquée |
| `tech_all` vs `tech_any` | deux requêtes distinctes, résultats différents |
| Favori en échec réseau | rollback + toast |
| Réinitialiser | retour aux **défauts**, visa inclus |
| Flux périmé | bandeau visible sur le feed |
| `axe` sur le panneau | zéro violation sérieuse |
| e2e Playwright | charger → filtrer → trier → favori → recharger l'URL → même écran |

---

## 7. Critères d'acceptation

- [ ] Les treize dimensions sont filtrables avec leurs comptes.
- [ ] L'état complet est dans l'URL, testé en aller-retour.
- [ ] **Le filtre visa par défaut inclut `unknown`**, vérifié par un test dédié.
- [ ] L'invariant **I6** est vérifié côté front.
- [ ] Les favoris sont optimistes avec rollback.
- [ ] Le bandeau de flux périmé s'affiche sur le feed.
- [ ] Le parcours e2e Playwright passe.
- [ ] `axe` sans violation sérieuse sur le feed et le panneau.
- [ ] `tsc --noEmit`, `eslint`, `vitest` passent.
