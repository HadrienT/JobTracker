# WP19 — La relecture complète par le LLM local

> **Contexte** : les règles (`normalize`) lisent vite et mal ; le LLM lit lentement et bien, mais
> peut inventer. Ce lot le laisse **relire toutes les offres et corriger leurs champs** —
> salaire, lieux, séniorité, visa, doctorat, date limite — sans jamais croire un mot qu'il n'a pas
> d'abord retrouvé dans le texte.

**Dépend de** : WP12 (voie LLM), ADR-006 (le LLM remplit des champs, jamais un score), ADR-010
(concurrence 1, pas de repli distant).

---

## 1. Le principe : rien n'est cru avant d'être retrouvé

Le modèle rend, pour chaque affirmation, une **citation copiée mot pour mot** de l'offre. Le
code vérifie (`match/review.py`, fonction pure) :

1. la citation figure dans l'offre (titre, champ lieu ou description) — casse et ponctuation
   ignorées, mots non ; l'étiquette de notre propre prompt (« Location field: ») n'est pas
   comptée contre elle ;
2. la valeur revendiquée figure **dans la citation** : un chiffre de salaire est un des nombres de
   sa citation (`175k`, `£95.000`, `1.2m` développés) ; une ville est un mot de sa citation ;
3. la citation **dit** la chose : un doctorat n'est « exigé » que si elle exprime une exigence
   (« the PhD internship is a 10-week program » n'en est pas une) ; « pas de visa » exige une
   exclusion (« we cannot sponsor »), pas une préférence (« we encourage citizens to apply ») ;
   un mode (sur site / hybride / télétravail) n'est retenu que si la citation le dit — un nom de
   ville n'est pas « on-site » ;
4. la valeur est plausible : devise connue, période citée cohérente avec celle annoncée, montant
   dans les bornes de sa période (`review.salary_bounds`), minimum ≤ maximum. Un montant
   **hebdomadaire** est refusé : le flux n'a pas de période « semaine » (et les règles, qui le
   rangeaient en « par an », ne le font plus).

Un salaire halluciné n'a donc aucune citation derrière laquelle se cacher, et une vraie citation
ne peut pas porter un chiffre qu'elle ne contient pas.

## 2. La politique d'application, volontairement dissymétrique

| | |
|---|---|
| **Combler** un champ que les règles n'ont pas trouvé | `llm.min_confidence` (0,6) |
| **Remplacer** une valeur que les règles avaient trouvée | `review.override_confidence` (0,8) |
| **Effacer** une valeur | jamais |
| `phd_required` | seulement `False → True` ; jamais l'inverse |
| Lieux | on **ajoute** les villes manquantes ; on ne retire jamais une ville ; sans aucune ville, celles du modèle remplacent le vide |
| `role_family` | **hors périmètre** : le titre décide, une lecture du corps ne doit pas la rebattre (le premier essai réel l'a montré : « Software Engineer Intern → quant_trading ») |

Une ville que le référentiel ignore n'est **pas inventée** : elle est rapportée en fin de run
(« cities missing from configs/geo.yaml »), à ajouter avec ses coordonnées.

## 3. Traçabilité et rejeu

- `llm_reviews` : quelles offres ont été lues, pour quel contenu (`content_hash`) et quelle
  version du prompt (`review.version`), avec quel résultat (`corrected` / `confirmed` /
  `set_aside`). Une offre lue n'est **pas relue** tant que ni son contenu ni la version ne
  changent ; monter `review.version` relance tout.
- `llm_corrections` : chaque champ changé, sa valeur **avant**, **après**, la **citation** et la
  confiance. Le panneau de détail les montre (« Corrected by the local LLM ») : aucune valeur n'a
  à être crue sur parole.
- Un **rejeu** (`just replay --apply`) ne remet pas ce que le texte contredisait : les champs
  corrigés sont protégés champ par champ, pour le contenu courant seulement.
- Les corrections modifient les champs ; le score est **recalculé** par `match.score` à partir des
  nouveaux champs (ADR-006), donc toujours explicable par ses `Reason`.

## 4. Exploitation

```bash
just llm-review --dry-run --limit 30 --report /tmp/r.jsonl   # ce qui CHANGERAIT ; n'écrit rien
just llm-review                                              # tout relire, meilleur score d'abord
just llm-review --posting-id 01M2…                           # une seule offre
```

- **`--dry-run` d'abord** : il passe par le même `plan_review` que le vrai run, donc ce qu'il
  affiche est ce que l'écriture ferait. `--report` écrit une ligne JSON par offre, avec la réponse
  brute du modèle.
- Le run s'arrête au **premier tour refusé** (serveur occupé ou éteint), tout ce qui précède est
  validé ; le suivant reprend là où il s'est arrêté.
- Rythme mesuré sur GPU : ~3 s par offre ; sur CPU (service parti avant le pilote), ~17 s.
- Les offres rejetées sont relues aussi (en dernier) : un rejet est un verdict que la lecture peut
  renverser.

## 5. Ce que les règles y ont gagné

La relecture a surtout servi de **détecteur de défauts des règles**, corrigés ensuite dans les
règles (donc pour toutes les offres, sans LLM) : « between $150,000 and $350,000 » lu comme un
montant unique ; un montant hebdomadaire rangé « par an » ; ~140 offres sans ville faute de
quinze villes absentes de `geo.yaml` et des lieux du type « Chicago Office » / « London and
Singapore ».

## 6. Limites

- Ce que le modèle ne cite pas, on ne le corrige pas : une information présente mais que le
  modèle ne sait pas citer reste aux règles.
- Un modèle qui cite fidèlement mais interprète mal (« we encourage citizens to apply » lu comme
  une exclusion) reste possible : les mots-repères réduisent ce risque, ne l'éliminent pas.
- Les corrections ne s'annulent pas d'un geste : la valeur d'avant est conservée dans
  `llm_corrections`, mais aucune commande de retour arrière n'existe encore.
