# WP18 — Suivi de candidature

> **Contexte** : le feed dit *quoi* regarder ; il ne se souvient de rien de ce que vous en avez
> fait. Ce lot ajoute votre côté de l'offre : où en est la candidature, et une note.

**Dépend de** : WP07 (API), WP10 (panneau de détail), WP11 (filtres).

---

## 1. Ce que fait le lot

- Un **statut** par offre : `applied`, `interview`, `offer`, `rejected` (refusé par eux),
  `withdrawn`. Absent = pas suivie. Modifiable dans le panneau de détail (une liste), enregistré
  dès qu'on change.
- Une **note** libre (4 000 caractères max), enregistrée en quittant le champ **et** à la
  fermeture du panneau : Échap démonte le panneau sans faire perdre le focus, et une note perdue
  ainsi serait le pire défaut d'un outil censé garder des pense-bêtes.
- Le statut apparaît en pastille à côté du titre dans le feed.
- Un filtre **Tracking** (panneau de filtres, pastille, URL `?statuses=applied&statuses=interview`)
  pour ne voir que ses candidatures.

## 2. Choix de conception

- **Stockage dans `user_flags`**, à côté de favori / masqué (migration `0006`), pour la même
  raison : ce sont des données de l'utilisateur, pas du pipeline. Un rescoring ou un rejeu ne
  peut pas les écraser, et une ligne `user_flags` exempte l'offre de la purge de rétention.
- **Une candidature survit à la fermeture de l'offre.** C'est le moment où l'on veut retrouver
  ce à quoi on a postulé : demander un statut lève la règle « offres actives seulement » (comme
  `favorites_only`). Sans cela, l'offre disparaîtrait du feed le jour où elle ferme.
- `CHECK` SQL sur les valeurs : une faute de frappe n'atteint jamais la table. `ApplicationStatus`
  est dans l'instantané des enums persistées (`tests/fixtures/enum_snapshot.json`).
- API : `POST /postings/{id}/status` (`{"status": null}` arrête le suivi), `POST
  /postings/{id}/note`. Le statut est dans la liste (`application_status`), la note seulement
  dans le détail.
- Mise à jour optimiste du statut, puis rechargement de la liste : un statut peut faire entrer ou
  sortir une offre d'une vue filtrée, ce qu'aucun correctif local ne sait.

## 3. Pastille « nouveau »

Un point sur les offres vues par le collecteur **après votre visite précédente**. La date de la
visite précédente est gardée en `sessionStorage` dès le premier chargement d'un onglet : un
rechargement ne fait pas vieillir ce que vous n'avez pas encore regardé. Première visite : rien
n'est « nouveau » (tout le serait, donc l'information est nulle). Stockage indisponible : pas de
pastille, jamais d'erreur.

## 4. Export et vues enregistrées

- **Export CSV** : `GET /export/postings.csv`, mêmes filtres et même tri que `/postings` (donc
  ce qu'on télécharge est ce qu'on regarde), parcourt toutes les pages en flux. Le bouton
  « Export CSV » du feed est un simple lien, que le navigateur télécharge.
- **Views** : des recherches nommées, gardées dans le navigateur (`localStorage`). Une vue n'est
  qu'une query string, la même que celle de la barre d'adresse : l'appliquer est une navigation,
  donc elle ne peut pas diverger de ce que les filtres veulent dire. Stockage indisponible ou
  corrompu : aucune vue, jamais une erreur.

## 5. Limites

- Pas d'historique des changements de statut (seule la date du dernier est gardée).
- Pas de rappel ni de date de relance.
- Le statut est global (un seul utilisateur, ADR-011).
