# WP09 — Front : fondations et design system

> **Contexte** : ce lot n'a **aucun prérequis**. C'est délibéré, et c'est ce qui
> rend le plan de parallélisation intéressant : une session peut construire tout
> le socle visuel pendant que deux autres écrivent le backend.
>
> La condition pour que ça marche est de coder **contre le contrat**, pas contre
> l'API. Les handlers MSW se dérivent de [03-INTERFACES.md](../03-INTERFACES.md)
> §3.6, et le jour où WP07 livre son schéma, le remplacement est un changement
> d'import.

**Fichiers à lire** : ce fichier · [12-WEB-UI.md](../12-WEB-UI.md) ·
[03-INTERFACES.md](../03-INTERFACES.md) §3.6 · [09-CONVENTIONS.md](../09-CONVENTIONS.md) §2, §4-5

**Dépend de** : rien. **Parallélisable avec** : tout.

---

## 1. Objectif

Un projet Vite qui compile, se lint, se teste, et porte les primitives visuelles
sur lesquelles WP10 et WP11 vont construire.

---

## 2. Outillage

| Élément | Choix |
|---|---|
| Build | Vite, React 19 |
| TypeScript | `strict: true`, `noUncheckedIndexedAccess: true`, **aucun `any`** |
| Style | Tailwind v4, tokens en variables CSS |
| Primitives | shadcn/ui, copiées dans `shared/ui/`, pas une dépendance opaque |
| Lint | eslint **bloquant** en CI — un lint non bloquant ne protège rien |
| Tests | vitest + RTL, `axe` pour l'accessibilité |
| Mocks | MSW, handlers dérivés du contrat |

Arborescence en [02-REPOSITORY-TREE.md](../02-REPOSITORY-TREE.md) §4 :
`app/ features/ shared/`. Pas de dossier `components/` fourre-tout — c'est le
premier pas vers un dossier de 90 fichiers sans structure.

---

## 3. Tokens

Thème **sombre par défaut**, thème clair disponible. Tokens en variables CSS sur
`:root`, redéfinis sous `[data-theme="light"]`.

| Famille | Contenu |
|---|---|
| Surfaces | fond, surface, surface élevée, bordure |
| Texte | primaire, secondaire, tertiaire (les champs « non dits ») |
| Sémantique | `strong`, `possible`, `stretch`, `rejected`, `warning`, `danger` |
| Visa | **trois** tokens distincts : `sponsors`, `unknown`, `no` |
| Typographie | une famille de texte, une famille **à chasse fixe tabulaire** pour tous les chiffres |

La chasse fixe tabulaire n'est pas un choix esthétique : sans elle, une colonne
de scores à trois chiffres ne s'aligne pas, et une liste dense devient illisible.

Les **trois tokens de visa** sont la traduction visuelle de P4. Un design à deux
couleurs pousserait à fusionner `unknown` avec l'un des deux, et le principe
serait perdu au premier écran.

---

## 4. Primitives de densité

Les composants que WP10 assemblera. Ils portent les règles d'affichage de
[12-WEB-UI.md](../12-WEB-UI.md) §3, une fois, au lieu de les réinventer.

| Composant | Rôle |
|---|---|
| `<Score>` | Chiffre tabulaire + pastille de palier, info-bulle des `Reason` |
| `<VisaBadge>` | **Trois rendus**, chacun avec glyphe **et** libellé — jamais la couleur seule |
| `<Money>` | Fourchette avec devise d'origine. **Absent = `—` gris**, jamais `0` |
| `<Age>` | `3d`, `2w`, `47d`, orange au-delà du seuil de péremption |
| `<Deadline>` | `closes in 6d`, rouge, absent quand la date est inconnue |
| `<LocationCell>` | `Ville PAYS` + mode, `+2` pour le multi-sites, `raw` au survol |
| `<Empty>` | Le rendu unique de « non dit » — **un seul endroit dans tout le front** |

`<Empty>` mérite d'exister comme composant : c'est ce qui garantit qu'un salaire
absent, une date absente et un visa inconnu se ressemblent partout, et qu'aucun
d'eux n'est jamais rendu comme un zéro.

---

## 5. MSW

Handlers pour les sept routes de [03-INTERFACES.md](../03-INTERFACES.md) §3.6,
avec un jeu de fausses offres **représentatif** :

- des offres à salaire absent, à visa inconnu, à lieu non résolu ;
- des offres multi-sites ;
- des titres très longs qui doivent tronquer proprement ;
- au moins 2 000 entrées, pour que la virtualisation de WP10 soit réellement
  éprouvée.

Un jeu de mocks trop propre donne un front qui casse à la première vraie donnée.

---

## 6. Tests attendus

| Test | Attendu |
|---|---|
| `tsc --noEmit` | aucune erreur, aucun `any` |
| `eslint` | zéro erreur, **bloquant** |
| `<Money>` sans montant | rend `<Empty>`, jamais `0` |
| `<VisaBadge>` sur les trois états | trois rendus distincts, chacun avec glyphe et libellé |
| `<Age>` au-delà du seuil | style d'avertissement |
| Bascule de thème | tous les tokens redéfinis, aucun contraste insuffisant |
| `axe` sur la page de démonstration des primitives | zéro violation sérieuse |
| `npm run build` | bundle initial **< 200 ko gzip** |

---

## 7. Critères d'acceptation

- [ ] `npm run dev`, `build`, `lint`, `test`, `tsc --noEmit` fonctionnent.
- [ ] CI front en place et **bloquante** sur le lint.
- [ ] Tokens définis pour les deux thèmes, y compris les **trois** états de visa.
- [ ] Les sept primitives du §4 existent avec leurs tests.
- [ ] `<Empty>` est le **seul** rendu de « non dit » du front.
- [ ] MSW sert les sept routes avec au moins 2 000 offres représentatives.
- [ ] Budget de bundle initial respecté et vérifié en CI.
- [ ] Une page de démonstration des primitives existe, et sert de référence visuelle.
