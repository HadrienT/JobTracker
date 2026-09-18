# WP12 — `match.llm` : préfiltre gratuit et LLM local

> **Contexte** : le scoring déterministe de WP05 tranche la grande majorité des
> offres. Ce lot résout le **résidu** — les cas où il faut lire un paragraphe
> pour décider.
>
> Le point à comprendre avant de coder : **le problème n'est pas le débit, c'est
> la collision**. Après préfiltrage, le LLM voit une dizaine d'offres par jour,
> soit deux ou trois appels en lots, soit **une trentaine de secondes de GPU par
> jour**. Ce n'est pas un problème de dimensionnement. Le seul risque réel est
> qu'un de ces appels tombe pendant une boucle agentique d'OpenHands, qui partage
> le même `llama-server`. C'est un problème d'**ordonnancement**.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) §2 (P5) ·
[10-PROFILE-TARGET.md](../10-PROFILE-TARGET.md) §7 · [decisions.md](../decisions.md) ADR-006, ADR-010 ·
[03-INTERFACES.md](../03-INTERFACES.md) §3.3 · `~/AgenticEnv/configs/models.yaml`

**Dépend de** : WP05 · WP08 (pour la voie différée).
**Parallélisable avec** : WP06 · WP10 · WP11.

---

## 1. Objectif

Deux choses, dans cet ordre : un **préfiltre gratuit** qui écarte ce qui ne peut
pas être ambigu, puis un **appel LLM** qui ne voit que le résidu.

---

## 2. L'entonnoir

```text
offres nouvelles / jour                     ~300
  après cache de content_hash               ~300   (les inchangées ne repassent pas)
  après rejet not_quant / excluded_title     ~90   (les banques publient massivement du non-quant)
  après rejet senior_only / phd_required     ~40
  après résolution déterministe complète     ~12   ← le résidu ambigu
  après préfiltre                             ~8   ← ce que le LLM voit
```

`tools/llm_load.py` recalcule ce tableau à partir des vraies mesures — les
hypothèses de volume sont en tête de fichier, à réajuster dès les premières
semaines de collecte.

Charge GPU correspondante, ordre de grandeur : ~8 offres par jour, lots de 4,
~1 500 jetons de contexte par offre, ~100 jetons de sortie. Sur le modèle servi
(`Qwen3-Coder-30B-A3B`, MoE à ~3 Md de paramètres actifs), cela représente
**quelques dizaines de secondes de GPU par jour**. Le coût n'est pas le sujet ;
la contention l'est.

---

## 3. Le préfiltre — ce qu'il écarte, et ce qu'il n'ose pas écarter

Le préfiltre écarte une offre du passage au LLM **seulement s'il est certain que
l'appel ne changerait rien au verdict**.

| Cas écarté sans appel | Justification |
|---|---|
| Rejet dur déjà prononcé (`senior_only`, `phd_required`, `stale`) | Aucune lecture ne les annulera |
| Score déterministe très au-dessus du seuil `strong`, tous champs résolus | Le LLM ne peut que confirmer |
| Score déterministe très en dessous de `stretch`, `role_family` résolu avec certitude | Idem |
| Description de moins de 200 caractères | Il n'y a rien à lire |

| Cas **envoyé** au LLM | Pourquoi les règles ne suffisent pas |
|---|---|
| `role_family` incertaine chez une société de rang 1 | « Software Engineer » chez un prop shop : il faut lire |
| `seniority == UNKNOWN` et description longue | L'information est là, mais pas sous une forme régulière |
| `visa == UNKNOWN` et pays hors UE | Le champ qui décide de la recevabilité (P4) |
| Contradiction titre / description | Il faut arbitrer, pas appliquer une priorité fixe |
| Langue non couverte par les motifs d'extraction | Les regex anglophones n'attrapent rien |
| Offre parapluie (« Graduate Opportunities 2026 ») | Un titre, huit rôles derrière |

**L'invariant I3 : zéro faux négatif.** Le préfiltre n'écarte que ce dont il est
certain. En cas de doute, il **laisse passer** — un appel LLM inutile coûte trois
secondes de GPU ; une offre écartée à tort disparaît sans laisser de trace, et
personne ne remarquera jamais son absence. L'asymétrie commande.

L'invariant se teste exhaustivement sur le corpus doré **et** par `hypothesis`.

---

## 4. L'appel

### 4.1 Contention avec OpenHands

`concurrency = 1` côté JobTracker, sans exception. Deux voies :

| Voie | Déclencheur | Comportement |
|---|---|---|
| **différée** (défaut) | tout le reste | File vidée toutes les 30 min. **Tour sauté** si le serveur est occupé |
| **urgente** | offre potentiellement `strong` chez une société de rang 1 | Tentative immédiate, timeout court. **Pas de repli distant** (ADR-010) |

La voie urgente ne change que le *moment* de l'appel, jamais sa priorité côté
serveur. **Aucune offre d'emploi n'est urgente à la minute** : un tour sauté
coûte trente minutes, c'est-à-dire rien. C'est la différence avec RamTracker, où
une enchère qui se termine justifiait un repli payant.

Détection d'occupation : sur `llama-server`, l'endpoint
`/health` a renvoyé 503 quand tous les slots étaient pris selon les versions, et
`/slots` expose l'état par slot. **Vérifier sur la version installée** plutôt que
de supposer, et prévoir le repli : un timeout court traité comme « occupé » est
un comportement correct par défaut.

### 4.2 Décodage contraint — non négociable

Espérer du JSON valide en le demandant poliment est une perte de temps. Le
décodage contraint garantit une sortie conforme au schéma et rend un modèle
local parfaitement fiable sur cette tâche précise.

**Confirmé** sur le `llama-server` installé (Qwen3-Coder-30B-A3B, 2026-09-18) :
`response_format: {"type": "json_schema", …}` est accepté et respecté — la
grammaire GBNF n'est pas nécessaire.

Une sortie non conforme au schéma est **rejetée** : l'offre reste sur son verdict
déterministe et part en quarantaine. Jamais de parsing indulgent.

### 4.3 Ce que le LLM renvoie

**Des champs, pas un score** (ADR-006).

```json
{
  "role_family": "quant_dev" | "swe_platform" | "quant_research" | ... ,
  "seniority": "graduate" | "junior" | "mid" | "senior" | "unknown",
  "min_years": 3,
  "visa_sponsorship": "sponsors" | "no" | "unknown",
  "phd_required": false,
  "confidence": 0.0
}
```

Le score est **recalculé par `match.score`** avec ces champs. C'est ce qui garde
le scoring reproductible et explicable : les `Reason` produites sont les mêmes,
seule leur entrée a changé, et `resolver_stage` passe à `"llm"`.

Un `confidence` bas laisse l'offre en quarantaine plutôt que de la promouvoir.

### 4.4 Le prompt

Énoncer explicitement les règles que le modèle enfreint :

```text
- Ne devine jamais. Un champ incertain vaut "unknown" ou null.
- visa_sponsorship="no" UNIQUEMENT si le texte exclut le sponsorship ou exige
  un droit de travailler préexistant. "Nous sommes dans l'impossibilité de
  sponsoriser" est un "no".
- Une restriction de lieu ("Remote, US only") vaut "no" pour un candidat externe.
- Si rien n'est dit sur le visa, la réponse est "unknown". Ce n'est pas "no".
- min_years = le minimum EXIGÉ, pas le maximum de la fourchette.
- "PhD preferred" n'est PAS phd_required. "PhD or equivalent experience" non plus.
- Un intitulé "Software Engineer" dans une société de trading est quant_dev ou
  swe_platform selon la description, jamais "other".
```

---

## 5. Tests attendus

| Test | Attendu |
|---|---|
| **I3**, exhaustif sur le corpus doré | aucune offre écartée par le préfiltre n'aurait changé de palier |
| **I3**, `hypothesis` | idem sur des `Posting` générés |
| Rejet dur déjà prononcé | **aucun** appel LLM |
| Description de 50 caractères | aucun appel |
| « Software Engineer » chez un prop shop, `role_family` incertaine | appel émis |
| Sortie non conforme au schéma | rejetée, quarantaine, **jamais** d'alerte |
| Serveur occupé, voie différée | remise en file, `attempts += 1`, aucun repli |
| Serveur occupé, voie urgente | tour sauté, verdict déterministe conservé |
| Serveur éteint | `LlmUnavailable`, run **poursuivi** |
| Concurrence sous charge simulée | **jamais** plus d'un appel simultané |
| Offre résolue par LLM | `resolver_stage == "llm"`, score **recalculé** par `match.score` |
| `confidence` bas | quarantaine, pas de promotion |

---

## 6. Critères d'acceptation

- [ ] L'invariant **I3** est couvert exhaustivement **et** par test de propriété.
- [ ] Aucun appel LLM n'est émis pour une offre écartée par le préfiltre.
- [ ] La concurrence côté JobTracker ne dépasse **jamais** 1, vérifié sous charge.
- [ ] Le décodage est contraint par schéma ; une sortie non conforme part en
      quarantaine plutôt qu'en verdict.
- [ ] **Aucun repli sur une API distante** (ADR-010) — vérifiable par `grep`.
- [ ] Le LLM ne produit **jamais** de score : il remplit des champs, le score est recalculé.
- [ ] `JT_LLM_ENABLED=false` : le système tourne normalement, tout reste déterministe.
- [ ] `tools/llm_load.py` produit le tableau d'entonnoir sur les données réelles.
- [ ] `match.prefilter` est **ajouté aux `source_modules` du contrat D8** ;
      `match.llm` en reste volontairement absent.
- [ ] `lint-imports` : `match.llm` est le **seul** module de `match` autorisé à
      faire de l'I/O — exception documentée au contrat D4/D8.
- [ ] `mypy --strict` passe.

---

## 7. Implémentation de la file (voie différée)

Le `llama-server` n'est pas toujours levé (il est partagé avec OpenHands, et
JobTracker ne le démarre jamais — pas de `sudo`, pas de repli distant). La file
est donc le mécanisme normal, pas l'exception :

| Élément | Où |
|---|---|
| Table `llm_queue` + colonne `postings.resolver_stage` | `migrations/0003_llm_queue.sql` |
| Persistance de la file | `store/llm_queue.py` |
| Traitement d'une entrée, vidage, tentative urgente | `runtime/residual.py` |
| Appel dans `ingest` | seulement pour une offre **nouvelle ou modifiée** (un re-fetch identique conserve le verdict, LLM compris) |
| Cadence | `jobtracker loop` vide toutes les 30 min ; `jobtracker llm-drain` à la main |

Un vidage **s'arrête au premier tour refusé** (pas de martelage) : l'offre reste
en file, `attempts += 1`, verdict déterministe intact. Une réponse non conforme
ou sous le seuil de confiance est retirée de la file (quarantaine) plutôt que
rejouée. `upsert_posting` ne réécrit rien pour un `content_hash` inchangé, d'où
`store.postings.update_resolution` : une résolution LLM change les champs sans
changer le contenu.
