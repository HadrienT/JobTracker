# WP10 — Front : couche données et feed virtualisé

> **Contexte** : le lot qui produit **l'écran du produit**. Tout le reste existe
> pour alimenter cette liste.
>
> La contrainte technique dominante est la virtualisation, et elle n'est pas une
> optimisation tardive : une liste de 15 000 offres rendue naïvement fige
> l'onglet. Le problème n'apparaît qu'une fois la base pleine — c'est-à-dire des
> semaines après avoir écrit le composant, quand le refactoriser coûte dix fois
> plus cher.

**Fichiers à lire** : ce fichier · [12-WEB-UI.md](../12-WEB-UI.md) §3, §5, §7 ·
[03-INTERFACES.md](../03-INTERFACES.md) §3.6 · [05-SEQUENCES.md](../05-SEQUENCES.md) §3 ·
`web/src/shared/ui/` livré par WP09

**Dépend de** : WP07 (contrat) · WP09. **Parallélisable avec** : WP08 · WP12.

---

## 1. Objectif

Types générés, client typé, hooks TanStack Query, liste virtualisée à pagination
infinie, volet de détail.

---

## 2. Couche API

| Élément | Règle |
|---|---|
| `schema.gen.ts` | **Généré** par `just types`, commité, jamais édité (ADR-005) |
| `client.ts` | Un seul constructeur de requête. Les en-têtes, la base d'URL et la normalisation d'erreurs y vivent **une fois** |
| `queries.ts` | Hooks TanStack Query, clés de cache structurées `['postings', filtre, tri]` |
| Erreurs | Normalisées en un type unique ; le composant affiche, il ne devine pas |
| Base d'URL | Lue depuis `window.__JT_CONFIG__`, **jamais** depuis `import.meta.env` ([12-WEB-UI.md](../12-WEB-UI.md) §9) |

Le piège à éviter est celui qu'on a déjà vu ailleurs : reconstruire les en-têtes
à la main dans chaque fonction d'appel. Un seul `client.ts`, et les hooks
l'utilisent.

---

## 3. Le feed

`useInfiniteQuery` + TanStack Virtual.

| Aspect | Règle |
|---|---|
| Taille de page | 50 |
| Préchargement | à 10 lignes de la fin |
| Nœuds DOM | **< 120** quel que soit le nombre d'offres |
| Hauteur de ligne | fixe, mesurée une fois — une hauteur variable ruine le calcul de défilement |
| Clé de cache | inclut le filtre **et** le tri : changer de tri est une nouvelle requête, pas un tri local |
| État vide | distinguer « aucun résultat sous ce filtre » de « le flux est vide » — deux messages, deux actions |
| Erreur | message + bouton de réessai, la liste déjà chargée **reste affichée** |

**Le tri est serveur, jamais client.** Trier 15 000 lignes dans le navigateur
demanderait de toutes les charger, ce qui annule la pagination. Le tri change la
requête.

---

## 4. Raccourcis clavier

| Touche | Action |
|---|---|
| `j` / `k` | ligne suivante / précédente, avec défilement suivi |
| `Entrée` | ouvre le volet de détail |
| `o` | ouvre l'annonce d'origine dans un nouvel onglet |
| `f` | bascule le favori |
| `h` | masque l'offre |
| `/` | focus sur la recherche |
| `Échap` | ferme le volet, puis vide la sélection |

Les raccourcis sont **désactivés** quand le focus est dans un champ de saisie —
sinon taper « job » dans la recherche masque trois offres.

---

## 5. Volet de détail

Route `/p/{id}`, rendue en volet par-dessus le flux : on ne perd pas sa position
de défilement.

Contenu : description complète, **raisons du score avec leurs extraits
justificatifs**, lieux, rémunération, visa avec son extrait, alias (« aussi sur
LinkedIn »), lien de candidature.

Les raisons du score sont l'élément le plus utile de cet écran : c'est là qu'on
voit que le parseur a lu « Senior » dans « Senior Java Developer, reporting to
the junior desk » et qu'on ouvre une issue.

Vraie modale : `aria-modal`, piège de focus, restitution du focus, `Échap`.

---

## 6. Tests attendus

| Test | Attendu |
|---|---|
| 2 000 offres mockées | **< 120** nœuds DOM |
| Scroll jusqu'à la page 5 | aucune offre dupliquée, aucune sautée |
| Changement de tri | nouvelle requête, position remise à zéro |
| Changement de filtre | nouvelle clé de cache, ancienne conservée en cache |
| Erreur réseau en page 3 | pages 1-2 toujours affichées, bouton de réessai |
| Aucun résultat sous filtre | message distinct de « flux vide » |
| `j`/`k` | sélection déplacée, défilement suivi |
| `f` dans un champ de recherche | **aucun** favori posé |
| Volet de détail | focus piégé, `Échap` ferme, focus restitué |
| `axe` sur le feed et le volet | zéro violation sérieuse |
| Dérive de schéma | `schema.gen.ts` régénéré == commité |

---

## 7. Critères d'acceptation

- [ ] Le feed affiche, pagine et scrolle 2 000 offres mockées sous les budgets de
      [12-WEB-UI.md](../12-WEB-UI.md) §7.
- [ ] Aucun type d'API écrit à la main.
- [ ] La base d'URL vient de `window.__JT_CONFIG__`, **pas** de `import.meta.env`.
- [ ] Tous les raccourcis du §4, inactifs en saisie.
- [ ] Le volet de détail est une modale accessible complète.
- [ ] Les raisons du score sont affichées avec leurs extraits.
- [ ] `tsc --noEmit`, `eslint`, `vitest` passent ; zéro `any`.
