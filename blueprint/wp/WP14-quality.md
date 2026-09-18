# WP14 — Qualité, tests, intégration continue

> **Contexte** : ce lot est en deux temps. Une **amorce** en vague 1, qui pose
> l'outillage pour que les autres lots aient une CI dès leur premier commit ; et
> une **passe complète** en vague 6, qui comble ce que les lots n'ont pas couvert.
>
> Il ne s'agit pas d'écrire les tests des autres lots — chaque lot livre les
> siens, c'est dans sa Definition of Done. Ce lot livre l'**infrastructure de
> test** et les tests **transverses** : ceux qui ne rentrent dans aucun package.

**Fichiers à lire** : ce fichier · [08-TESTING.md](../08-TESTING.md) **en entier** ·
[09-CONVENTIONS.md](../09-CONVENTIONS.md) §8

**Dépend de** : WP01 pour l'amorce. **Parallélisable avec** : tout.

---

## 1. Amorce (vague 1)

- [ ] `pytest` configuré avec les cinq marqueurs de [08-TESTING.md](../08-TESTING.md) §1
      et `--strict-markers`.
- [ ] `conftest.py` : base temporaire migrée, horloge figée, `Settings` de test,
      faux `HttpSession` rejouant une charge utile figée.
- [ ] `.github/workflows/ci.yml` avec les trois jobs, **aucun accès réseau**.
- [ ] `just ci` reproduit les trois jobs localement.
- [ ] Squelette de `tests/fixtures/` avec son `README.md` d'étiquetage.

Les fixtures partagées sont ce qui évite que chaque lot réinvente sa base
temporaire. Le faux `HttpSession` en particulier débloque WP06 avant que WP04 ne
soit fini ([dependencies.md](../dependencies.md) §5).

---

## 2. Passe complète (vague 6)

### 2.1 Tests de discipline

Des tests qui vérifient les **règles du projet**, pas son comportement. Ils
attrapent ce qu'aucune revue ne rattrape sur la durée.

| Test | Vérifie |
|---|---|
| `grep` de `datetime.now()` hors `clock.py` | règle N6 |
| `grep` de `float(` dans les chemins monétaires | règle N2 |
| `grep` de `OFFSET` dans `store/` | ADR-007 |
| `grep` de `urllib.request` / `http.client` hors `collect` et `match.llm` | contrat D8 — `import-linter` ne peut pas lister ces sous-modules de la stdlib |
| Aucun littéral de seuil dans `match/` | interdit n°1 |
| Aucun `except: pass` ni `except Exception: pass` | interdit n°2 |
| Chaque `Source` a un collecteur ou est marquée non implémentée | cohérence du registre |
| Chaque motif de rejet produit par `match` est dans une liste connue | stabilité des identifiants |
| `.env.example` contient toutes les variables lues par `Settings` | règle C5 |
| Chaque valeur de `StrEnum` persistée a une migration si elle est nouvelle | |

Ces tests sont peu élégants et très rentables : ils encodent les interdits du
PRIMER sous une forme exécutable, ce qui les rend vérifiables par une machine au
lieu d'une relecture.

### 2.2 Couverture du corpus doré

- [ ] **200 offres** étiquetées, quotas de [WP00](WP00-recon-registry.md) §4 respectés.
- [ ] Le tableau de résolution par étage est produit par `just test-golden`.
- [ ] **Une baisse du taux de résolution échoue le build.** Les seuils vivent dans
      un fichier versionné, relevés délibérément quand on progresse.

### 2.3 e2e

Playwright contre la stack `docker compose`, base de démonstration figée.

Parcours : charger → filtrer par pays → ajouter un filtre stack → trier par date
→ ouvrir un détail → mettre en favori → recharger l'URL → retrouver le même écran
avec le favori.

### 2.4 Accessibilité et régression visuelle

`axe` sur le feed, le panneau de filtres et le volet de détail. Captures de
référence sur les deux thèmes pour les primitives de densité.

---

## 3. CI

| Job | Contenu | Bloquant |
|---|---|---|
| `backend` | `ruff check` · `ruff format --check` · `mypy --strict` · `lint-imports` · `pytest -m "not live"` | ✅ |
| `frontend` | `tsc --noEmit` · `eslint` · `vitest run` · `npm run build` + contrôle de budget | ✅ |
| `api-contract` | `just types` puis `git diff --exit-code` sur les deux fichiers générés | ✅ |
| `e2e` | Playwright sur la stack compose | ✅ en vague 6 |

Aucun job n'a accès au réseau vers les sources : tout `live` est exclu par
construction. Un test qui dépend de la disponibilité de Greenhouse rendra la CI
rouge un jour, sans rapport avec le code.

---

## 4. Critères d'acceptation

- [ ] Les cinq marqueurs et `--strict-markers` sont en place.
- [ ] Les fixtures partagées du §1 existent et sont utilisées par au moins trois lots.
- [ ] Les dix tests de discipline du §2.1 passent.
- [ ] Le corpus doré atteint **200 offres** avec ses quotas.
- [ ] Une baisse du taux de résolution **échoue le build**.
- [ ] Le parcours e2e passe sur la stack compose.
- [ ] `axe` sans violation sérieuse sur les trois écrans.
- [ ] Les quatre jobs CI sont verts et bloquants.

---

## 5. État de livraison

Ce qui est fait, et ce qui ne l'est pas — sans arrondi.

**Fait**

- Amorce (§1) : cinq marqueurs + `--strict-markers` ; fixtures partagées
  `frozen_clock` et `settings_factory` (`tests/conftest.py`), utilisées par plus de
  trois modules de tests (`test_match_rules`, `test_match_score`, `test_match_prefilter`,
  `test_match_llm`, `test_aggregators_isolation`) ; `just ci` reproduit les jobs
  `backend`, `frontend`, `api-contract`.
- Tests de discipline (§2.1) : `tests/test_discipline.py`, en **AST** et non en `grep` —
  un commentaire qui *mentionne* `datetime.now()` ne doit pas casser le build. Le test
  « aucun littéral de seuil dans `match/` » a trouvé de vrais manquements (les constantes
  de WP12 : confiance minimale, marge de haute confiance, longueur minimale de
  description, fenêtre de fraîcheur) ; ils vivent désormais dans `configs/profile.yaml`
  (`freshness:` et `llm:`), pas dans le code.
- Plancher de résolution (§2.2) : `tests/fixtures/postings/resolution_floors.json`,
  versionné ; `just test-golden` imprime le taux par étage **et** son plancher, et une
  baisse fait échouer le test. Un second test interdit d'abaisser un plancher sous sa
  valeur de livraison.
- e2e (§2.3) : `scripts/e2e.sh` — base de démo figée (`tools/seed_demo_db.py`, le corpus
  doré passé par le vrai chemin `ingest` sous horloge figée), images `api` et `web` de
  la stack de production sur un projet compose à part (`docker-compose.e2e.yml`),
  démontage garanti. Le parcours du §2.3 lit les réponses de l'API, pas seulement le DOM.
- Accessibilité et visuel (§2.4) : `axe` sur le feed, les filtres et le détail, **dans les
  deux thèmes** ; captures de référence des primitives de densité, dans les deux thèmes.
- CI : job `e2e` bloquant ; job `e2e-visual` **informatif** (voir plus bas).

**Ce que l'e2e a trouvé** (et qui est corrigé) : ouvrir puis fermer un détail effaçait les
filtres de l'URL (`routing.ts` poussait `/p/{id}` et `/` sans la query string) ; la liste
était un `listbox` dont chaque `option` contenait le bouton favori (`nested-interactive`,
`aria-required-children`) — devenue `grid`/`row`/`gridcell` ; le contraste du texte tertiaire
et du vert / ambre du thème clair était sous 4,5:1.

**Non atteint**

- **Corpus à 200 offres** : il en compte 71. Étiqueter à la main est le but du corpus ; les
  étiqueter par le code qu'on teste le viderait de sa valeur. Le quota reste à faire par
  le mainteneur (voir `tests/fixtures/postings/README.md`).
- **Captures visuelles en CI** : les références ont été produites sur la machine du
  mainteneur ; les polices système diffèrent d'un runner à l'autre. Tant qu'elles ne sont
  pas régénérées sur le runner (`just e2e --update-snapshots`, relire, commiter), le job
  `e2e-visual` est `continue-on-error`. Le job `e2e` (parcours + axe) est bloquant.
- La CI GitHub elle-même n'a pas été exécutée : reproduite localement, pas sur un runner.

