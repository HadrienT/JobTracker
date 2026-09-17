# WP04 — `collect` : socle HTTP et trois familles d'ATS

> **Contexte** : le premier lot qui touche le réseau. Il livre deux choses de
> nature très différente — une **politique HTTP** partagée par tous les
> collecteurs présents et futurs, et **trois collecteurs** qui sont presque
> triviaux une fois la politique en place.
>
> Le rapport d'effort est volontairement déséquilibré : la politique mérite
> l'essentiel du soin. Greenhouse, Lever et Ashby sont des API publiques propres,
> destinées à l'agrégation ; leurs parseurs font trente lignes chacun. Ce qui
> coûte, c'est de bien se comporter : une requête à la fois, avec gigue, avec
> repli exponentiel, avec un budget — parce que c'est cette politique que WP06 et
> WP13 réutiliseront sur des sources bien moins tolérantes.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) §5 ·
[11-SOURCES.md](../11-SOURCES.md) §1-2, §6 · [03-INTERFACES.md](../03-INTERFACES.md) §3.1 ·
[07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md) §1 · [08-TESTING.md](../08-TESTING.md) §3

**Dépend de** : WP01 · WP02. **Parallélisable avec** : WP03 · WP05.

---

## 1. Objectif

`base.py`, `http.py`, `registry.py`, et les collecteurs Greenhouse, Lever, Ashby.

---

## 2. `http.py` — la politique, écrite une fois

| Règle | Valeur | Pourquoi |
|---|---|---|
| Concurrence par hôte | **1** | Interdit n°7. Un board ne mérite pas d'être martelé |
| Gigue entre requêtes | `configs/sources.yaml`, 2-7 s | Un rythme régulier à la milliseconde est une signature de bot |
| Repli sur 429/403 | exponentiel, base 30 s, plafond 1 h | Interdit n°8 |
| Budget de requêtes par run | plafonné par source | Un board à pagination cassée peut boucler à l'infini |
| Dépassement de budget | `truncated=True`, **aucune exception** | La collecte partielle vaut mieux que rien |
| Timeout | 20 s | |
| `ETag` / `If-Modified-Since` | utilisés quand servis | Gratuit, et divise le volume transféré |
| `User-Agent` | honnête et identifiable | On ne se déguise pas sur une API publique conçue pour l'agrégation |

Le **budget de requêtes** mérite un mot : sans lui, une pagination mal
interprétée (un ATS qui renvoie toujours la même page) tourne jusqu'au timeout du
processus. Avec lui, elle s'arrête à 200 requêtes et remonte `truncated=True`,
qui est un signal exploitable par le chien de garde.

`HttpSession` est un `Protocol` ([03-INTERFACES.md](../03-INTERFACES.md) §3.1).
**Un collecteur qui construit son propre client HTTP est un bug** — `import-linter`
ne le verra pas, c'est à la revue de le voir.

---

## 3. Les trois collecteurs

Endpoints en [11-SOURCES.md](../11-SOURCES.md) §2, tous `[À CONFIRMER]` par les
sondes de WP00.

| Famille | Particularités de mapping |
|---|---|
| **Greenhouse** | `content=true` donne la description en HTML échappé. `location.name` est du texte libre. `metadata` peut porter des champs personnalisés utiles |
| **Lever** | `categories.location`, `categories.commitment` (`Full-time`/`Intern` — **précieux pour la séniorité**), `lists` porte des sections structurées |
| **Ashby** | `includeCompensation=true` donne de vraies fourchettes quand la société les publie. `isListed` à `false` = offre masquée, **à ignorer** |

Chaque collecteur fait trois choses : appeler, valider en `RawPosting`, archiver
la charge utile. **Il n'interprète rien** : le texte de lieu part brut dans
`location_raw`, la date brute dans `posted_at_raw`. L'interprétation est le
travail de WP03, et la faire ici la rendrait intestable.

---

## 4. `registry.py`

Lit `configs/companies.yaml`, valide en `list[Board]`, produit le plan de
collecte : quelles sociétés, dans quel ordre, à quelle cadence selon leur
`priority`.

Une entrée invalide **empêche le démarrage** avec un message qui nomme le slug —
pas un `enabled: false` silencieux. Le registre est du code source (ADR-009), et
un code source invalide ne compile pas.

---

## 5. Erreurs — la distinction qui compte

| Réponse | Erreur | Conséquence |
|---|---|---|
| Timeout, 5xx, DNS | `SourceUnavailable` | retry court, le disjoncteur compte |
| 403, 429, challenge | `SourceBlocked` | **repli exponentiel long**, disjoncteur ouvert |
| 404 sur un jeton | `BoardNotFound` | **`ERROR`, remonte à un humain** : le registre est faux |
| 200, charge utile méconnaissable | `SourceSchemaChanged` | `ERROR`, le parseur est périmé |
| 200, liste vide | **pas une erreur** | `source_runs(status="empty")`, aucune désactivation d'offre |

La dernière ligne est la plus importante du lot : elle implémente la branche
critique de [05-SEQUENCES.md](../05-SEQUENCES.md) §4. **On ne désactive jamais
d'offre sur un run à zéro.**

---

## 6. Tests attendus

Tous en `contract`, sur charges utiles figées, **sans réseau**.

| Test | Attendu |
|---|---|
| Réponse nominale, par famille | bon nombre d'offres, champs mappés |
| Board vide | 0 offre, **aucune exception** |
| 404 | `BoardNotFound`, pas `SourceUnavailable` |
| 429 | `SourceBlocked`, **aucun retry immédiat** (vérifié par une horloge factice) |
| Charge utile méconnaissable | `SourceSchemaChanged` |
| Champ obligatoire manquant sur une offre | offre ignorée avec log, run poursuivi |
| Budget atteint | `truncated=True` |
| Ashby `isListed=false` | offre ignorée |
| Lever `commitment="Intern"` | conservé dans `RawPosting` pour WP03 |
| Gigue | deux requêtes consécutives espacées d'au moins le minimum configuré |
| `ETag` servi | seconde requête conditionnelle, 304 traité |

---

## 7. Critères d'acceptation

- [ ] `Collector` est un `Protocol` de quatre lignes, respecté par les trois collecteurs.
- [ ] **Aucun collecteur ne construit son propre client HTTP.**
- [ ] Aucun collecteur n'écrit en base ni n'interprète le contenu d'une offre.
- [ ] Les cinq cas d'erreur du §5 sont distingués et testés.
- [ ] Un run à zéro offre produit `status="empty"` et **aucune désactivation**.
- [ ] La charge utile brute est archivée pour **chaque** offre collectée.
- [ ] `just run-once --source greenhouse` collecte réellement sur au moins
      20 boards du registre et remonte des offres.
- [ ] `lint-imports` : contrat **D5** vert.
- [ ] `mypy --strict` passe.
