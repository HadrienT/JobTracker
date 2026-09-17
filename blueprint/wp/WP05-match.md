# WP05 — `match` : la qualification déterministe

> **Contexte** : le lot qui donne son sens au flux. Sans lui, JobTracker est un
> agrégateur de plus ; avec lui, c'est un filtre sur un profil précis.
>
> La contrainte structurante : **le score doit être explicable**. « Pourquoi cette
> offre est-elle à 78 ? » a une réponse exacte, affichée dans l'UI, dérivée d'une
> somme de contributions tracées. C'est ce qui permet de corriger le scoring quand
> il se trompe — et il se trompera, souvent, les premières semaines.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[10-PROFILE-TARGET.md](../10-PROFILE-TARGET.md) **en entier** ·
[03-INTERFACES.md](../03-INTERFACES.md) §2.4, §3.3 · [06-CONFIG.md](../06-CONFIG.md) §3

**Dépend de** : WP00 (corpus) · WP03. **Parallélisable avec** : WP04 · WP06 · WP07.

---

## 1. Objectif

`evaluate(posting, *, profile) -> MatchVerdict`, ses rejets durs, sa grille de
poids, et `configs/profile.yaml`. **Zéro I/O** (contrat D4).

---

## 2. L'ordre d'évaluation

```text
1. rejets durs        → tier=REJECTED, rejection_reason, score non calculé
2. contributions      → somme des Reason(code, delta, evidence)
3. bornage            → score ∈ [0, 100]
4. palier             → seuils de configs/profile.yaml
```

Les rejets durs court-circuitent : inutile de calculer un score pour une offre de
VP à Singapour. Mais l'offre est **stockée** avec son motif — c'est ce qui permet
de mesurer le bruit par source et de rejouer après un changement de profil.

---

## 3. Les rejets durs

| Motif | Condition | Piège |
|---|---|---|
| `not_quant` | `role_family == other` | Ne jamais rejeter sur `swe_platform` : c'est le même métier sous un autre nom chez un prop shop |
| `senior_only` | `min_years > 4`, ou titre `senior`/`lead`/`principal`/`staff`/`vp`/`head` | `"Staff Engineer"` est senior ; `"Staffing Coordinator"` ne l'est pas — délimiter le mot |
| `phd_required` | doctorat exigé **sans** « ou expérience équivalente » | « PhD preferred » n'est **pas** un rejet |
| `stale` | plus vieille que `stale_after_days` | Sur la date calculée de [09-CONVENTIONS.md](../09-CONVENTIONS.md) §3, pas `posted_at` brut |
| `excluded_title` | titre dans `profile.titles.excluded` | |

**`Seniority.UNKNOWN` n'est jamais un rejet.** Une offre qui ne dit rien est
souvent ouverte, et rejeter sur le silence fait disparaître des opportunités sans
laisser de trace. Même logique que `visa=unknown` (P4).

---

## 4. Les contributions

Grille en [10-PROFILE-TARGET.md](../10-PROFILE-TARGET.md) §6, valeurs dans
`configs/profile.yaml`. **Aucun nombre dans le code** (interdit n°1).

Chaque contribution produit un `Reason(code, delta, evidence)` :

```python
Reason(code="visa_no", delta=-25,
       evidence="We are unable to provide visa sponsorship for this role.")
```

`evidence` est l'extrait de texte qui a déclenché la contribution. Il est affiché
dans le détail de l'offre, et c'est **l'outil de débogage du scoring** : quand
une offre est mal classée, on voit immédiatement quelle phrase a été mal lue.

`sector_tier1` se lit dans le **registre**, pas dans l'annonce. C'est ce qui
permet de valoriser un « Software Engineer » chez Optiver sans valoriser le même
titre chez un intégrateur quelconque.

---

## 5. Versionnement du profil

`configs/profile.yaml` porte `version:`. Le verdict porte `profile_version`.

Conséquence : au démarrage, le runtime rescore les offres dont le
`profile_version` est périmé, **et seulement celles-là**. Sans ce champ, changer
un poids laisse 16 000 offres avec l'ancien score, en silence — et on croit que
le changement n'a rien fait.

Changer un poids **impose** d'incrémenter `version`. C'est dans la Definition of
Done.

---

## 6. Tests attendus

| Test | Attendu |
|---|---|
| Corpus doré, offres étiquetées avec leur palier attendu | concordance, aucune régression |
| **I5** : `tier=REJECTED` ⟺ `rejection_reason` non nul | exhaustif |
| `"Staff Engineer"` | `senior_only` |
| `"Staffing Coordinator"` | `excluded_title`, **pas** `senior_only` |
| `"PhD preferred"` | **pas** de rejet |
| `"PhD required"` | `phd_required` |
| `"PhD or equivalent experience"` | **pas** de rejet |
| `seniority=UNKNOWN`, `min_years=None` | recevable, score calculé |
| `"Software Engineer"` chez un prop shop de rang 1 | `possible` ou mieux |
| `"Software Engineer"` chez un éditeur de rang 3 | score nettement inférieur |
| `visa=NO` | −25 appliqué, `evidence` renseigné |
| `visa=UNKNOWN` | **aucune** pénalité |
| Score borné | jamais < 0 ni > 100 |
| Même offre, deux évaluations | verdict identique (déterminisme) |
| Poids modifié sans changement de `version` | test d'hygiène qui **échoue** |

---

## 7. Critères d'acceptation

- [ ] `evaluate` et `hard_reject` respectent [03-INTERFACES.md](../03-INTERFACES.md) §3.3.
- [ ] **Aucun poids, seuil ou liste de titres dans le code** — vérifiable par revue et par un test qui charge un profil alternatif.
- [ ] Chaque contribution produit un `Reason` avec son `evidence` quand un extrait existe.
- [ ] L'invariant **I5** est couvert exhaustivement.
- [ ] Le corpus doré porte un palier attendu par offre, et la concordance est un test.
- [ ] `profile_version` est propagé dans chaque verdict.
- [ ] `lint-imports` : contrat **D4** vert, **aucun import réseau**.
- [ ] Les modules créés (`profile`, `rules`, `score`, `reasons`) sont **ajoutés
      aux `source_modules` du contrat D8** dans `pyproject.toml` — ils y sont
      énumérés un par un parce que `match.llm` est l'exception à préserver.
- [ ] `mypy --strict` passe.
