# 12 — Le front

> Prérequis : [00-PRIMER.md](00-PRIMER.md), [03-INTERFACES.md](03-INTERFACES.md) §3.6.
> À lire si vous touchez `web/`.

---

## 1. Ce qu'on vise

**Un terminal de lecture d'offres, pas un job board grand public.** Le mètre
étalon : on doit pouvoir évaluer une offre en **une ligne**, et en parcourir cent
en deux minutes. Trois qualités, dans cet ordre :

1. **Densité.** Une offre = une ligne, lisible sans clic. Pas de carte avec
   logo, pas de vignette, pas d'espace blanc décoratif. Un écran de 1440p montre
   ~35 offres, pas 6.
2. **Vérité sur l'état.** Chaque donnée affichée dit ce qu'elle vaut : un salaire
   absent n'est pas « 0 », un visa inconnu n'est pas « non », une offre de
   quarante jours est affichée comme telle. Un champ gris et daté vaut mieux
   qu'un champ faux et confiant.
3. **Vitesse au clavier.** `j`/`k` pour naviguer, `f` pour mettre en favori, `o`
   pour ouvrir l'annonce, `/` pour chercher. Scroller une liste de 15 000 offres
   à la souris n'est pas un mode d'usage.

Thème **sombre par défaut**, chiffres en chasse fixe tabulaire, aucune animation
au-delà de 150 ms.

---

## 2. Pile technique

| Rôle | Choix |
|---|---|
| Build | Vite, React 19, TypeScript `strict` + `noUncheckedIndexedAccess` |
| Style | Tailwind v4, tokens en variables CSS, shadcn/ui pour les primitives |
| Données | TanStack Query (cache, retry, invalidation) |
| Virtualisation | TanStack Virtual — **obligatoire**, la liste dépasse 10 000 lignes |
| Types d'API | `schema.gen.ts` **généré**, jamais écrit à la main (ADR-005) |
| État des filtres | **l'URL**, via `URLSearchParams`. Pas de store global |
| Mocks | MSW, fixtures dérivées du schéma généré — permet de coder WP09 avant l'API |
| Tests | vitest + RTL, Playwright pour l'e2e, axe pour l'accessibilité |

---

## 3. La ligne d'offre

C'est l'élément le plus regardé du produit. Il porte, dans cet ordre de lecture :

```text
┌────────────────────────────────────────────────────────────────────────────────────┐
│ 87 │ Quantitative Developer (C++)          Optiver        Amsterdam NL   onsite    │
│ ●  │ graduate · 0-2y · cpp python          ✓ sponsors     €—             3d  ★     │
└────────────────────────────────────────────────────────────────────────────────────┘
  │                                              │                          │    │
  │ score + pastille de palier                   │ visa, 3 états visibles   │    └ favori
  └ chasse fixe, aligné, triable                 └ salaire ou tiret         └ âge
```

| Élément | Règle d'affichage |
|---|---|
| Score | Chiffre en chasse fixe + pastille de palier. Survol = les `Reason` qui l'ont produit |
| Titre | Le titre nettoyé. Le titre brut au survol, parce que le nettoyage est une hypothèse |
| Société | Cliquable → filtre sur la société. Le secteur en info-bulle |
| Lieu | `Ville PAYS` + mode (`onsite` / `hybrid` / `remote`). Multi-lieux : `Londres +2` |
| Visa | **Trois rendus distincts** : `✓ sponsors` (vert), `✗ no visa` (rouge), `? visa` (gris). Jamais deux |
| Salaire | Fourchette avec devise **d'origine**, jamais convertie. Absent = `—` gris, pas `0` |
| Âge | `3d`, `2w`, `47d`. Au-delà de la moitié de `stale_after_days`, en orange |
| Clôture | `closes in 6d` en rouge quand elle existe — voir [10-PROFILE-TARGET.md](10-PROFILE-TARGET.md) §5 |
| Alias | Un `+2` discret quand l'offre existe sur d'autres sources |

**Ce qu'on n'affiche pas dans la ligne** : le logo, la description, le
département, le nombre de candidats. Tout ça dilue la densité pour une
information qu'on ne lit pas en scrollant.

---

## 4. Filtres et facettes

Panneau latéral persistant, chaque dimension avec son **compte sous le filtre
courant** (invariant I6 de [08-TESTING.md](08-TESTING.md)).

| Dimension | Contrôle |
|---|---|
| Pays | liste à cocher, triée par compte |
| Ville | recherche + cases, alimentée par les facettes |
| Mode | onsite / hybrid / remote |
| Société | recherche + cases |
| Secteur | prop_trading, hedge_fund, bank, asset_manager, vendor, crypto |
| Séniorité | intern / graduate / junior / mid / unknown |
| Stack | cases ET/OU, avec bascule explicite « toutes » / « au moins une » |
| **Visa** | trois cases : `sponsors`, `unknown`, `no`. **Défaut : les deux premières** |
| Palier / score min | curseur |
| Publiée depuis | 24 h / 7 j / 30 j / tout |
| Recherche | plein texte FTS5, avec `/` comme raccourci |
| Favoris | bascule |

**Deux règles non négociables :**

1. **L'état complet des filtres est dans l'URL.** L'écran est partageable,
   rechargeable, et le bouton Précédent fonctionne. Un bug de filtre se rapporte
   en collant l'URL dans l'issue.
2. **Le filtre visa par défaut n'exclut pas `unknown`.** C'est le rappel de P4
   dans l'UI : le réglage par défaut ne doit jamais faire disparaître
   silencieusement des offres recevables.

---

## 5. Tri

| Clé | Comportement |
|---|---|
| `score` (défaut) | décroissant, départagé par `posting_id` — sinon la pagination keyset saute des lignes |
| `posted` | le plus récent d'abord, sur la date calculée de [09-CONVENTIONS.md](09-CONVENTIONS.md) §3 |
| `seen` | date de première détection par le système |
| `closes` | date de clôture croissante, les offres sans clôture en dernier |
| `company` | alphabétique |

---

## 6. Écrans

| Écran | Contenu |
|---|---|
| **Feed** (`/`) | La liste virtualisée + le panneau de filtres. **C'est le produit** |
| **Détail** (`/p/{id}`) | Description complète, raisons du score avec leurs extraits justificatifs, alias, lien de candidature. Ouvrable en volet sans quitter le flux |
| **Companies** (`/companies`) | Registre : nombre d'offres, dernière collecte réussie, santé. Sert à repérer une société muette |
| **Health** (`/health`) | Rendu de `GET /health` : sources dégradées, fraîcheur du flux. Un bandeau d'alerte apparaît sur le feed quand le flux est périmé |

---

## 7. Performance

| Budget | Valeur |
|---|---|
| JS initial (gzip) | **< 200 ko** |
| Première ligne affichée | < 1,5 s en local |
| Nœuds DOM du feed | < 120 quel que soit le nombre d'offres (virtualisation) |
| Chargement de page suivante | 50 offres par page, préchargement à 10 lignes de la fin |
| Facettes | requête **parallèle** à la liste, jamais bloquante |

La virtualisation n'est pas une optimisation tardive : c'est une contrainte de
départ. Une liste de 15 000 offres rendue naïvement fige l'onglet, et on ne s'en
rend compte qu'une fois la base pleine — c'est-à-dire trop tard pour que ce soit
un petit correctif.

---

## 8. Accessibilité

- Navigation clavier complète, ordre de focus visible.
- Le volet de détail est une vraie modale : `aria-modal`, piège de focus,
  restitution du focus à la fermeture, `Échap` pour fermer.
- Les pastilles de palier et de visa ne reposent **pas uniquement sur la
  couleur** : elles portent un glyphe et un libellé.
- `axe` sans violation sérieuse sur le feed et le panneau de filtres, vérifié en CI.

---

## 9. Configuration au runtime — le piège Vite

Les variables `VITE_*` sont **inlinées à la compilation**. Une `VITE_API_BASE`
oblige à reconstruire l'image pour changer d'URL d'API, et pousse tôt ou tard à
mettre un secret dans le bundle.

Le front lit sa configuration depuis un `/config.js` servi par nginx et généré au
démarrage du conteneur :

```html
<script src="/config.js"></script>   <!-- window.__JT_CONFIG__ = { apiBase: "…" } -->
```

C'est la seule façon d'avoir une image de front **identique** en local et en
production. Voir [wp/WP15-deploy.md](wp/WP15-deploy.md).
