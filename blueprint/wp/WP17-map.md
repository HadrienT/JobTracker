# WP17 — L'onglet Carte

> **Contexte** : le feed se scrolle, la carte se **regarde**. Même données, mêmes filtres,
> même URL d'état — un autre point d'entrée : « où recrute-t-on, et combien ? ».

**Dépend de** : WP07 (API), WP10 (feed, panneau de détail), WP11 (filtres).

---

## 1. Ce que fait l'écran

- Une carte du monde, un **pin par ville** (taille selon le nombre d'offres), sous **les mêmes
  filtres que le feed** (panneau de filtres, pastilles, URL). Changer un filtre déplace les pins.
- Un pin qui porte **une seule offre** ouvre directement le panneau de détail.
- Un pin qui en porte **plusieurs** ouvre un tiroir à droite : la liste des offres, meilleur score
  d'abord, avec « Load more ». Ce tiroir n'est pas modal : on peut choisir un autre pin sans le
  fermer. Choisir une offre ouvre le panneau de détail par-dessus ; le fermer (✕, Échap, clic sur
  la zone assombrie) ramène à la carte, tiroir ouvert.
- `/map` est l'écran ; `/map/p/{id}` le détail par-dessus. La query string (filtres) est
  conservée dans les deux sens.
- Un compteur dit combien d'offres n'ont **pas de ville** (télétravail, pays seul, non résolue) :
  elles ne sont pas sur la carte, et ne disparaissent pas en silence.

## 2. Données

- **Coordonnées** : `configs/geo.yaml` porte `lat` / `lon` (centre-ville, WGS84) pour chaque
  ville. Obligatoires : une ville sans coordonnées est une erreur de configuration, pas un pin
  manquant. `tests/test_core_geo.py` garde contre le piège qui compte — un signe inversé qui
  placerait Chicago dans le Pacifique — par une boîte englobante par pays.
- **`GET /map/pins`** : mêmes paramètres de filtre que `/postings` ; répond
  `{pins: [{city, country, lat, lon, count, posting_id|null}], total, unplaced}`. `posting_id`
  n'est renseigné que si `count == 1`.
- **Comptage** : une offre compte **une fois** par pin (`COUNT(DISTINCT)`) et peut figurer sous
  plusieurs pins (une offre ouverte à New York et à Londres). Les filtres de lieu (`countries`,
  `cities`, `remote_modes`) s'appliquent aussi à la **ligne** de localisation : filtrer sur
  `countries=US` ne laisse pas un pin à Londres.
- **`place_country` + `place_city`** sur `/postings` : un lieu précis, testé sur **une seule**
  ligne de localisation (Londres GB n'est pas Londres CA). C'est ce que le tiroir demande, donc
  la liste et le pin ne peuvent pas diverger sur ce que « ce pin » veut dire. L'un sans l'autre :
  422.

## 3. Rendu

- **SVG dessiné localement** (`d3-geo`, projection Natural Earth ; `world-atlas` 50 m servi comme
  asset statique). Pas de fond de carte tiers : la CSP n'autorise que l'origine, et un tableau
  de bord d'offres n'a pas à appeler un fournisseur de cartes à chaque page vue.
- La carte est **chargée à la demande** (`React.lazy`) : le bundle principal n'en paie rien
  (≈ +12 Kio gzip sur l'onglet, hors du budget initial).
- Molette / boutons pour zoomer, glisser pour déplacer, réinitialiser. Les pins gardent leur
  taille à l'écran quel que soit le zoom. Chaque pin est un vrai bouton (Tab, Entrée, Espace)
  nommé « Ville, PAYS — N postings ».

## 4. Limites connues

- Les pins de villes proches se **chevauchent** au zoom initial (Europe de l'Ouest, côte est des
  États-Unis) : il faut zoomer. Pas de regroupement automatique (clustering) pour l'instant.
- Une offre **sans ville** n'est pas sur la carte. Placer un pays entier au centroïde serait
  inventer un lieu : ce n'est pas fait.
- Le fond de carte à 50 m pèse ≈ 240 Kio gzip, chargé une fois.
