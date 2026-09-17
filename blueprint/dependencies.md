# Matrice de parallélisation

> **À lire au démarrage de tout lot de travail.**
>
> Ce fichier existe pour une raison précise : plusieurs sessions Claude Code
> travaillent en parallèle sur ce dépôt. Il répond à trois questions — *mes
> prérequis sont-ils faits ?*, *quels fichiers ai-je le droit d'écrire ?*, *que
> faire quand j'ai besoin d'un contrat qui n'existe pas encore ?*

---

## 1. Protocole de démarrage de session

```sh
gh issue list --state open                 # ce qui est en cours et par qui
git fetch --all && git branch -r           # les branches de lot actives
```

1. Choisir un lot dont **tous les prérequis sont clos** (§2).
2. Vérifier dans §3 qu'aucune branche active ne tient les mêmes fichiers.
3. Créer la branche `wpNN-nom-court`, ouvrir ou s'assigner l'issue.
4. Lire, dans l'ordre : [00-PRIMER.md](00-PRIMER.md),
   [09-CONVENTIONS.md](09-CONVENTIONS.md), puis le fichier du lot et **uniquement**
   les documents qu'il liste.

**Une session = un lot = une branche.** Deux lots dans la même session finissent
en un commit impossible à relire.

---

## 2. Vagues de parallélisme

Chaque vague suppose la précédente terminée. À l'intérieur d'une vague, **tous
les lots sont simultanés**.

| Vague | Lots simultanés | Sessions utiles | Débloque |
|---|---|---|---|
| **0 — Socle partagé** | *bootstrap* (§6) | **1 seule**, avant tout le reste | tout |
| **1 — Racines** | **WP00** · **WP01** · **WP09** · WP14(amorce) | jusqu'à 4 | WP02, WP03, WP10 |
| **2 — Socle métier** | **WP02** · **WP03** | 2 | WP04, WP05, WP07 |
| **3 — Corps** | **WP04** · **WP05** · **WP07** | 3 | WP06, WP08, WP10 |
| **4 — Écran + couverture** | **WP06** · **WP08** · **WP10** | 3 | WP11, WP12, WP13 |
| **5 — Finition** | **WP11** · **WP12** · **WP16** | 3 | WP13, WP15 |
| **6 — Risque & industrialisation** | **WP13** · **WP14**(complet) · **WP15** | 3 | — |

**Le point important de la vague 1 : trois lots sans aucun prérequis.** WP00 est
de la reconnaissance (réseau et YAML), WP01 du code de socle, WP09 du front avec
MSW. Ils ne partagent pas un seul fichier. C'est la configuration idéale pour
démarrer trois sessions simultanées dès la première minute.

---

## 3. Propriété des fichiers

**Règle d'or : un fichier a un propriétaire par vague.** Un lot écrit ses
fichiers, lit ceux des autres, et ne modifie **jamais** un fichier dont il n'est
pas propriétaire sans passer par §4.

| Lot | Écrit (exclusif) | Lit seulement |
|---|---|---|
| **WP00** | `configs/companies.yaml` · `tools/probe_ats.py` · `tests/fixtures/payloads/**` · `tests/fixtures/postings/corpus.jsonl` · `blueprint/11-SOURCES.md` | — |
| **WP01** | `src/jobtracker/core/**` · `configs/geo.yaml` | — |
| **WP02** | `src/jobtracker/store/**` · `migrations/**` | `core/**` |
| **WP03** | `src/jobtracker/normalize/**` · `configs/taxonomy.yaml` | `core/**` · corpus doré |
| **WP04** | `src/jobtracker/collect/base.py` · `http.py` · `registry.py` · `ats/{greenhouse,lever,ashby}.py` | `core/**` · `configs/companies.yaml` · fixtures de charges utiles |
| **WP05** | `src/jobtracker/match/{profile,rules,score,reasons}.py` · `configs/profile.yaml` | `core/**` · `normalize/**` · corpus doré |
| **WP06** | `src/jobtracker/collect/ats/{workday,smartrecruiters,workable,recruitee,personio,custom}.py` | `collect/{base,http}.py` |
| **WP07** | `src/jobtracker/api/**` · `web/openapi.json` · `web/src/api/schema.gen.ts` | `core/**` · `store/**` |
| **WP08** | `src/jobtracker/runtime/{cli,scheduler,breaker,watchdog,pipeline}.py` | tout le reste de `src/` |
| **WP09** | `web/` **sauf** `src/api/schema.gen.ts`, `src/features/**` | — |
| **WP10** | `web/src/api/{client,queries}.ts` · `web/src/features/feed/**` · `web/src/mocks/**` | `web/src/shared/**` · `schema.gen.ts` |
| **WP11** | `web/src/features/{filters,favorites}/**` | `web/src/features/feed/**` |
| **WP12** | `src/jobtracker/match/{prefilter,llm}.py` · `tools/llm_load.py` | `match/**` · `runtime/pipeline.py` |
| **WP13** | `src/jobtracker/collect/aggregators/**` | `collect/{base,http}.py` · `normalize/dedup.py` |
| **WP14** | `tests/**` (hors fixtures de WP00) · `.github/workflows/**` · `web/tests/**` | tout |
| **WP15** | `deploy/**` · `docker-compose*.yml` · `Dockerfile*` | tout |
| **WP16** | `src/jobtracker/runtime/{replay,report}.py` · `src/jobtracker/store/retention.py` | tout |

### Fichiers réellement partagés

Quatre fichiers sont touchés par presque tous les lots. Ce sont les seuls points
de conflit structurels du dépôt.

| Fichier | Qui y touche | Protocole |
|---|---|---|
| `pyproject.toml` | tout lot ajoutant une dépendance ou un contrat `import-linter` | **Un commit dédié, en début de lot**, poussé immédiatement sur `main`. Jamais mélangé au code du lot |
| `justfile` | tout lot ajoutant une tâche | Idem : commit dédié, ajout en fin de fichier, jamais de réorganisation |
| `.env.example` | tout lot ajoutant un paramètre | Idem, plus la mise à jour de [06-CONFIG.md](06-CONFIG.md) |
| `src/jobtracker/core/models.py` · `enums.py` | tout lot ajoutant un champ à un DTO | Voir §4 — **c'est le cas sérieux** |

La règle « commit dédié poussé tôt » règle 90 % des conflits : un ajout d'une
ligne en fin de fichier fusionne tout seul, un fichier réorganisé au milieu d'un
lot de 2 000 lignes ne fusionne jamais.

---

## 4. Changer un contrat partagé

[03-INTERFACES.md](03-INTERFACES.md) est le contrat qui rend le parallélisme
possible. Le modifier au milieu d'un lot casse potentiellement trois sessions en
cours.

**Procédure, sans raccourci :**

1. **Ouvrir une issue** `contract: <quoi>` décrivant le champ ou la signature à
   changer, et qui en dépend.
2. **Un commit isolé sur `main`** contenant : la mise à jour de
   `03-INTERFACES.md`, le champ ajouté dans `core/models.py` ou `enums.py`, et la
   migration si le champ est persisté.
3. **Prévenir les lots concernés** en commentaire de leurs issues.
4. Les lots rebasent. Le champ est **optionnel** (`| None`, valeur par défaut)
   tant que tous les producteurs ne le remplissent pas.

**Ajouter** un champ optionnel ou une valeur de `StrEnum` est peu risqué.
**Renommer** ou **retirer** demande une migration et casse les URL partagées
(les `StrEnum` sont dans les query params du front) — à traiter comme une
rupture, pas comme un nettoyage.

---

## 5. Démarrer un lot avant que son prérequis ne soit fini

Souvent possible, et c'est ce qui donne le vrai parallélisme.

| Lot | Attend | Peut démarrer avec |
|---|---|---|
| **WP03** (normalize) | WP00 pour le corpus | Une dizaine d'offres copiées à la main dans `corpus.jsonl`. Le corpus complet arrive ensuite et révèle les vrais cas |
| **WP05** (match) | WP03 pour de vrais `Posting` | Des `Posting` construits à la main dans les tests. Le DTO est figé par [03-INTERFACES.md](03-INTERFACES.md) §2.3 |
| **WP07** (api) | WP02 pour `list_postings` | Les signatures de [03-INTERFACES.md](03-INTERFACES.md) §3.5 et une implémentation bouchon. **La forme de l'OpenAPI ne dépend pas du SQL** |
| **WP09/WP10** (front) | WP07 pour l'API | **MSW**. Les handlers se dérivent du contrat §3.6, et l'écran se construit entièrement sur des mocks. C'est pour ça que WP09 n'a aucun prérequis |
| **WP06** (ATS 2) | WP04 pour `HttpSession` | Le `Protocol` de §3.1. Un faux `HttpSession` qui rejoue une charge utile figée suffit à écrire et tester le parseur |
| **WP13** (agrégateurs) | WP03 pour le dédoublonnage | **Non.** Ici on attend vraiment : allumer un agrégateur sans dédoublonnage testé triple la taille apparente du flux |

**Le motif général** : on code contre le *contrat*, pas contre
l'*implémentation*. Le lot en aval écrit un bouchon minimal, le lot en amont
livre la vraie version, et le branchement est un remplacement d'import.

---

## 6. Vague 0 — le socle partagé, une seule fois

Avant d'ouvrir plusieurs sessions, **une session** pose les fichiers que tout le
monde touche, pour qu'ils n'aient plus à l'être :

- [ ] `pyproject.toml` : dépendances de base, `ruff`, `mypy`, `pytest`, les neuf
      contrats `import-linter` D1→D9 (même si les packages sont vides)
- [ ] `justfile` : toutes les tâches de [CLAUDE.md](../CLAUDE.md), même celles
      qui échouent encore
- [ ] `.env.example` complet, d'après [06-CONFIG.md](06-CONFIG.md) §1
- [ ] `.gitignore`
- [ ] Les répertoires de packages avec leur `__init__.py` vide, pour que
      `import-linter` ait quelque chose à vérifier
- [ ] `.github/workflows/ci.yml` avec les trois jobs de [08-TESTING.md](08-TESTING.md) §7
- [ ] `uv sync` et un premier commit sur `main`

Sans cette vague, les trois premières sessions créent chacune leur
`pyproject.toml` et la fusion est une soirée perdue.

---

## 7. Graphe inverse — qui casse quoi

À consulter avant de modifier un composant existant.

| Si vous changez… | Vérifiez |
|---|---|
| `core/models.py` ou `enums.py` | **tous** les lots · les migrations · `schema.gen.ts` · les URL de filtres du front |
| `normalize/dedup.py` (empreinte) | WP13 · l'invariant I4 · **les offres déjà en base ne seront pas ré-empreintées** sans rejeu explicite |
| `configs/profile.yaml` | incrémenter `version:` — sinon les offres déjà scorées gardent l'ancien score en silence |
| `configs/taxonomy.yaml` | idem, et relancer `just test-golden` : le taux de résolution par étage doit monter, jamais baisser |
| une route ou un schéma d'API | `just types` **dans le même commit**, sinon le job `api-contract` casse |
| `collect/http.py` | tous les collecteurs, y compris ceux de WP13 |
| le schéma SQL | une migration `NNNN_*.sql`, jamais une modification en place |
| `store/facets.py` | l'invariant I6 · le panneau de filtres du front |

---

## 8. Ce qu'on ne parallélise pas

| Travail | Pourquoi une seule session |
|---|---|
| La vague 0 (§6) | Tout le monde touche les mêmes quatre fichiers |
| Un changement de contrat (§4) | Par construction, il traverse les lots |
| Le schéma SQL initial (WP02) | Deux migrations `0001_*` concurrentes sont irréconciliables |
| `collect/http.py` (WP04) | Politique unique ; deux versions concurrentes donnent deux comportements de repli |
| L'étiquetage du corpus doré | C'est un travail de jugement, pas de code. Il se fait en continu, par petites touches, dans le lot qui rencontre le cas |
