# WP08 — `runtime` : ordonnanceur, disjoncteur, chien de garde

> **Contexte** : le lot qui transforme un ensemble de composants en système
> autonome. Il porte la composition (`pipeline.py`), la cadence (`scheduler.py`),
> la résistance à la panne (`breaker.py`) et — le plus important — la détection
> du **silence** (`watchdog.py`).
>
> Le chien de garde inversé mérite qu'on s'y attarde, parce qu'il est
> contre-intuitif : il ne surveille pas les erreurs, il surveille **l'absence de
> résultats**. Un système de collecte qui casse ne lève pas d'exception ; il
> remonte zéro, et zéro ressemble au calme plat du marché. Sans ce composant, on
> découvre au bout de trois semaines que Greenhouse ne remonte plus rien depuis
> le 4 du mois.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) §2 (P3) ·
[05-SEQUENCES.md](../05-SEQUENCES.md) §1, §4 · [07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md) ·
[06-CONFIG.md](../06-CONFIG.md) §4

**Dépend de** : WP02 · WP04 · WP05. **Parallélisable avec** : WP10.

---

## 1. Objectif

`cli.py`, `scheduler.py`, `breaker.py`, `watchdog.py`, `pipeline.py`. À la fin de
ce lot, `just loop` tourne seul et `just status` dit la vérité.

---

## 2. `pipeline.py` — l'ordre des étapes

L'ordre de [05-SEQUENCES.md](../05-SEQUENCES.md) §1, avec deux points qui ne sont
pas négociables :

1. **L'archive brute est écrite avant la normalisation.** Si le normaliseur plante
   sur une offre exotique, la charge utile est déjà en base et le rejeu la
   reprendra. L'ordre inverse perd précisément les cas intéressants.
2. **Le dédoublonnage précède le scoring.** Scorer un alias brûle du CPU — et du
   GPU si le LLM s'en mêle — pour une ligne qui ne sera jamais affichée.

---

## 3. `scheduler.py`

| Aspect | Règle |
|---|---|
| Cadence par source | `configs/sources.yaml`, `interval_min` |
| Cadence par société | `priority` du registre : 1 = chaque cycle, 2 = quotidien, 3 = hebdomadaire |
| Ordre des boards | Mélangé à chaque cycle | 
| Gigue | Entre boards **et** entre requêtes |
| Concurrence | 1 par source. Deux sources différentes peuvent avancer en parallèle |

**Mélanger l'ordre des boards** n'est pas cosmétique : un ordre alphabétique fixe
fait que les sociétés en fin d'alphabet sont toujours celles qui tombent quand le
budget de requêtes est atteint. Elles deviennent silencieusement sous-collectées.

---

## 4. `breaker.py`

Disjoncteur par source, trois états.

| État | Déclencheur | Comportement |
|---|---|---|
| Fermé | normal | On collecte |
| **Ouvert** | N échecs consécutifs, ou un `SourceBlocked` | On saute, `status="skipped"`, pour une durée exponentielle |
| Demi-ouvert | fin du délai | **Un seul** board de test. Succès → fermé, échec → ouvert avec délai doublé |

Un `SourceBlocked` ouvre **immédiatement**, sans compter les échecs : c'est
l'interdit n°8 appliqué au niveau du système.

L'état du disjoncteur est **persisté** dans `source_runs`. Un redémarrage de
processus ne doit pas réinitialiser un disjoncteur ouvert — sinon un redémarrage
automatique après crash martèle joyeusement la source qui vient de nous bloquer.

---

## 5. `watchdog.py`

Les quatre alertes de [07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md) §4 :

| Alerte | Détection |
|---|---|
| `source_mute` | N runs consécutifs à `status="empty"` |
| `source_stalled` | Aucun run depuis 3 × l'intervalle configuré |
| `volume_drop` | `last_count` sous 20 % de la médiane glissante des 10 derniers runs |
| `feed_stale` | Aucune offre nouvelle, toutes sources confondues, depuis `global_stale_hours` |

`volume_drop` attrape ce que les autres ratent : une source qui passe de 300 à 40
offres n'est pas vide, donc pas `mute`, mais elle est probablement cassée — un
ATS qui change de pagination sert souvent la première page puis s'arrête.

La **médiane** glissante, pas la moyenne : une seule valeur aberrante ne doit pas
déplacer la référence.

---

## 6. `cli.py`

```sh
jobtracker migrate
jobtracker run-once --source greenhouse [--company optiver]
jobtracker loop
jobtracker status                       # code retour 1 si dégradé
jobtracker probe --company <slug>       # une société, en verbeux, pour déboguer
```

`status` sort avec le **code retour 1** en état dégradé. C'est ce qui permet de
le brancher sur une supervision, une tâche cron ou un contrôle avant déploiement
sans écrire une ligne de plus.

---

## 7. Tests attendus

| Test | Attendu |
|---|---|
| Run complet sur des collecteurs factices | offres normalisées, scorées, stockées |
| Offre qui fait planter le normaliseur | log, run **poursuivi**, charge utile en base |
| Board en erreur | log, board suivant collecté |
| N échecs consécutifs | disjoncteur ouvert |
| `SourceBlocked` unique | disjoncteur ouvert **immédiatement** |
| Demi-ouvert, test réussi | fermé |
| Demi-ouvert, test échoué | ouvert, délai **doublé** |
| Redémarrage du processus | disjoncteur ouvert **conservé** |
| N runs vides | `watchdog_alert(source_mute)` |
| Volume divisé par 8 | `watchdog_alert(volume_drop)` |
| Une valeur aberrante isolée | **pas** d'alerte (médiane) |
| `status` en état dégradé | code retour **1** |
| Ordre des boards sur 5 cycles | ordres différents |

---

## 8. Critères d'acceptation

- [ ] `just loop` tourne en continu sans fuite ni dérive de cadence.
- [ ] L'archive brute est écrite **avant** la normalisation, vérifié par un test
      où le normaliseur lève.
- [ ] Le dédoublonnage précède le scoring.
- [ ] Le disjoncteur est **persisté** et survit à un redémarrage.
- [ ] Les quatre alertes du chien de garde sont implémentées et testées.
- [ ] `just status` sort en code 1 en état dégradé.
- [ ] Un run à zéro offre ne désactive **aucune** offre.
- [ ] `lint-imports` : contrat **D7** vert (personne n'importe `runtime`).
- [ ] `mypy --strict` passe.
