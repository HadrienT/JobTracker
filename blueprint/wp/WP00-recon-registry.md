# WP00 — Reconnaissance & registre d'entreprises

> **Contexte** : c'est le lot qui construit l'actif principal du projet. Tout le
> reste est de la plomberie autour de lui.
>
> Le point à comprendre avant de commencer : **un jeton de board faux est
> indiscernable d'une société qui ne recrute pas**. `boards-api.greenhouse.io/v1/
> boards/optivr/jobs` renvoie une 404 qu'un collecteur mal écrit avalera, ou pire,
> un 200 avec une liste vide. Dans les deux cas le flux est silencieusement amputé
> d'une société, et personne ne s'en aperçoit. La seule parade est de **vérifier
> chaque jeton par une sonde réelle**, une fois, et de garder la trace de cette
> vérification.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) §2 (P1) ·
[11-SOURCES.md](../11-SOURCES.md) · [06-CONFIG.md](../06-CONFIG.md) §2 ·
[08-TESTING.md](../08-TESTING.md) §2-3

**Dépend de** : rien. **Parallélisable avec** : WP01 · WP09 · WP14.

---

## 1. Objectif

Trois livrables, dans cet ordre :

1. `tools/probe_ats.py` — l'outil qui sonde un candidat sur toutes les familles
   d'ATS et dit laquelle répond.
2. `configs/companies.yaml` — **150 sociétés minimum**, chacune avec sa famille
   et son jeton **vérifiés**, ou `enabled: false` avec la raison.
3. `tests/fixtures/` — les charges utiles de référence par famille, et l'amorce
   du corpus doré.

---

## 2. `tools/probe_ats.py`

```sh
uv run python tools/probe_ats.py --name "Optiver" --guess optiver
uv run python tools/probe_ats.py --url https://www.optiver.com/working-at-optiver/career-opportunities/
uv run python tools/probe_ats.py --all --save          # re-sonde tout le registre
```

Ce qu'il fait :

| Étape | Détail |
|---|---|
| Génération de candidats | À partir du nom : `optiver`, `optiverus`, `optiver-global`… |
| Sondage | Chaque famille de [11-SOURCES.md](../11-SOURCES.md) §2-3, séquentiellement, avec gigue |
| Discrimination | 200 avec une liste **non vide** = trouvé. 200 avec liste vide = **douteux**, à revérifier à la main |
| `--url` | Récupère la page carrière et cherche les motifs d'URL d'ATS dans le HTML et les scripts |
| `--save` | Écrit la charge utile dans `tests/fixtures/payloads/<famille>/<slug>.json` |
| Sortie | Ligne YAML prête à coller dans `companies.yaml` |

**Le cas « 200 avec liste vide » est le plus important.** Il signifie soit que la
société ne recrute vraiment pas, soit que le jeton appartient à quelqu'un
d'autre. L'outil ne doit **jamais** le classer comme un succès : il le marque
`# [À CONFIRMER] board vide au sondage du <date>`.

---

## 3. Construire le registre

Ordre de travail, par rendement décroissant :

1. **Rang 1** de [11-SOURCES.md](../11-SOURCES.md) §4 — prop shops et hedge
   funds. Ce sont les employeurs les plus pertinents pour la cible, et ils
   utilisent massivement Greenhouse / Lever / Ashby. Rendement maximal.
2. **Banques** — presque toutes sous Workday. Le sondage demande d'inspecter la
   page carrière pour trouver `{tenant}`, `{n}` et `{site}`. Compter ~10 min par
   banque, et le noter dans `extra:`.
3. **Éditeurs, asset managers, crypto** — mélange de tout.
4. Le résidu en `source: custom`, `enabled: false`, avec un commentaire.

**Ne pas deviner un jeton.** Une ligne non vérifiée est pire qu'une ligne
absente : elle donne l'illusion de la couverture.

---

## 4. Le corpus doré d'amorce

Objectif de ce lot : **60 offres étiquetées**, réparties sur au moins cinq
familles d'ATS et quatre pays. La cible finale de 200 s'atteint en continu, au
fil des bugs rencontrés par les autres lots.

Critères de sélection des offres, pour que le corpus soit utile :

| Critère | Pourquoi |
|---|---|
| Au moins 10 offres **sans** mention de séniorité | C'est le cas majoritaire, et celui où les parseurs naïfs inventent |
| Au moins 10 avec un visa **explicitement refusé** | Le cas qui coûte le plus cher à rater |
| Au moins 10 en langue autre que l'anglais | Les annonces françaises et néerlandaises cassent les regex anglophones |
| Au moins 5 « Software Engineer » chez un prop shop | Le piège de classification de [10-PROFILE-TARGET.md](../10-PROFILE-TARGET.md) §2 |
| Au moins 5 offres multi-sites | « London / New York / Hong Kong » sur une seule annonce |
| Au moins 5 avec fourchette de salaire | Devises et périodes différentes |
| Quelques offres franchement hors sujet | Ventes, RH — la classe `other` doit être testée aussi |

Format en [08-TESTING.md](../08-TESTING.md) §2. Les offres sont **anonymisées**
de tout contact nominatif : on archive du texte d'annonce, pas des coordonnées de
recruteur.

---

## 5. Tests attendus

| Test | Attendu |
|---|---|
| `companies.yaml` se charge en `list[Board]` | aucune erreur de validation |
| Tous les `slug` sont uniques et en `snake_case` | |
| Toute entrée `enabled: true` a un `token` non vide | |
| Toute entrée `source: workday` a `extra.site` et `extra.wd` | |
| Toute entrée non vérifiée porte un commentaire `[À CONFIRMER]` | vérifié par un test qui lit le YAML brut |
| Le corpus doré se charge et chaque entrée a un bloc `expect` complet | |
| Chaque famille d'ATS a au moins une charge utile de référence | prérequis des tests de contrat de WP04/WP06 |

---

## 6. Critères d'acceptation

- [ ] `tools/probe_ats.py` fonctionne sur les trois modes (`--name`, `--url`, `--all`).
- [ ] **150 sociétés minimum** dans `companies.yaml`, dont les 25 du rang 1.
- [ ] **Chaque `token` de chaque entrée `enabled: true` a été vérifié par une
      sonde réelle**, et la date du sondage est en commentaire.
- [ ] Un board vide au sondage est marqué `[À CONFIRMER]`, jamais validé.
- [ ] Au moins une charge utile de référence par famille d'ATS implémentée en WP04.
- [ ] **60 offres** étiquetées dans le corpus doré, respectant les quotas du §4.
- [ ] [11-SOURCES.md](../11-SOURCES.md) mis à jour : tout `[À CONFIRMER]` levé
      est remplacé par l'endpoint réel, dans le même commit.
