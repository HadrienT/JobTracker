# WP01 — `core` : le noyau partagé

> **Contexte** : tous les autres packages en dépendent, et aucun ne peut être
> écrit proprement avant lui. C'est la moitié du chemin critique — l'autre étant
> WP02.
>
> Le piège de ce lot est la tentation du fourre-tout. `core` porte les **types**,
> les **primitives** et les **frontières** ; il ne porte aucune logique métier.
> Si vous vous surprenez à écrire une regex d'extraction dans `core`, elle
> appartient à `normalize`.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[09-CONVENTIONS.md](../09-CONVENTIONS.md) · [03-INTERFACES.md](../03-INTERFACES.md) §1-2 ·
[06-CONFIG.md](../06-CONFIG.md) · [07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md)

**Dépend de** : rien. **Parallélisable avec** : WP00 · WP09 · WP14.

---

## 1. Objectif

Les onze modules de [02-REPOSITORY-TREE.md](../02-REPOSITORY-TREE.md) §2, avec
leurs tests. À la fin de ce lot, `mypy --strict` et `lint-imports` passent sur un
projet où seul `core` est rempli.

---

## 2. Les modules qui demandent une décision

### `config.py`

`Settings` pydantic-settings, préfixe `JT_`, plus le chargement des YAML de
`configs/`. **Seul endroit du projet qui lit `os.environ` ou ouvre un fichier de
configuration** (règle C2).

Un YAML invalide **empêche le démarrage**, avec un message qui nomme le fichier,
le champ et la ligne (règle C3). Pas de valeur par défaut silencieuse : une
cadence absente qui retombe sur 60 minutes est un bug qu'on découvre six semaines
plus tard.

### `clock.py`

```python
def utc_now() -> datetime: ...          # aware UTC, toujours
def freeze(at: datetime) -> ContextManager[None]: ...   # pour les tests
```

**Aucun autre module du projet n'appelle `datetime.now()`.** C'est la condition
pour que l'invariant I2 (déterminisme du normaliseur) soit testable : sans
horloge figeable, « publiée il y a 3 jours » change entre deux exécutions du
corpus.

### `money.py`

`Money(amount: Decimal, currency: str)`. Les opérations inter-devises sont
**explicites et datées** : pas d'addition implicite d'un EUR et d'un USD. La
conversion n'existe que pour l'affichage et porte son taux et sa date.

Rappel de l'interdit n°5 : **on ne convertit jamais à l'écriture en base**. Une
offre à `£65,000–£85,000` reste en livres, pour toujours.

### `geo.py`

Le référentiel ville → (pays, région, alias). Chargé depuis `configs/geo.yaml`.

Les **pièges d'homonymie** sont à traiter dès ce lot, pas plus tard :

| Ville | Ambiguïté | Désambiguïsation |
|---|---|---|
| Cambridge | UK / Massachusetts | `hq_country` de la société, puis fuseau du reste de l'annonce |
| London | UK / Ontario | idem — mais UK par défaut dans notre contexte sectoriel |
| Birmingham | UK / Alabama | idem |
| Saint-Pétersbourg | Russie / Floride | idem |

Le choix retenu est **journalisé** avec son indice. Un lieu non résolu donne
`Location(city=None, country=None, raw="…")` — jamais une invention.

### `hashing.py`

Deux fonctions à ne pas confondre :

| Fonction | Sur quoi | Sert à |
|---|---|---|
| `content_hash(title, description, location)` | le contenu brut | détecter qu'une offre a **changé**, pour éviter un rescoring inutile |
| `fingerprint(company, title, country, posted_at)` | la normalisation | **dédoublonner entre sources** ([03-INTERFACES.md](../03-INTERFACES.md) §3.4) |

`content_hash` est sensible à la moindre virgule, c'est voulu. `fingerprint` est
délibérément insensible : c'est sa raison d'être.

### `payloads.py`

Compression zstd, `pack()` / `unpack()`. Niveau 3, largement suffisant : une
description d'offre compresse d'un facteur 4 à 6, et on en stocke 150 000 par an.

### `errors.py`

Toute la taxonomie de [07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md) §1,
**et rien d'autre nulle part ailleurs**. Un package qui définit son exception
maison casse la capacité du runtime à classer les pannes.

### `db.py`

Connexion, pragmas (`journal_mode=WAL`, `busy_timeout=5000`, `foreign_keys=ON`,
`synchronous=NORMAL`), `apply_migrations()`, gestionnaire de transaction.

Les pragmas sont posés **ici et nulle part ailleurs**. Une connexion ouverte
ailleurs sans WAL produit des `SQLITE_BUSY` intermittents, c'est-à-dire un bug
qui ne se reproduit pas.

---

## 3. Tests attendus

| Test | Attendu |
|---|---|
| `Settings` sur un `.env` complet | tous les champs typés, aucun `Any` |
| `.env` avec une variable manquante et sans défaut | échec au démarrage, message nommant la variable |
| YAML invalide | `ConfigError` nommant fichier + champ |
| `utc_now()` sous `freeze()` | valeur figée, aware, UTC |
| `Money` : addition EUR + USD | `TypeError`, pas une conversion implicite |
| `Decimal` → base → `Decimal` | aller-retour exact, aucun flottant intermédiaire |
| `geo` : « Cambridge » avec `hq_country=US` vs `GB` | deux résolutions distinctes, toutes deux journalisées |
| `geo` : lieu inconnu | `city=None`, `raw` conservé |
| `fingerprint` : même offre, titres avec `(f/h)` et `2026 start` | empreinte **identique** |
| `fingerprint` : deux offres distinctes de la même société | empreintes **différentes** |
| `content_hash` : description modifiée d'un caractère | hachage différent |
| `pack`/`unpack` | aller-retour identique, y compris sur de l'UTF-8 accentué |
| `db` : pragmas | WAL actif, `foreign_keys` à 1, sur une base neuve |

---

## 4. Critères d'acceptation

- [ ] Les onze modules existent avec leurs signatures de [03-INTERFACES.md](../03-INTERFACES.md).
- [ ] `mypy --strict` passe sur `core`, aucun `Any` en signature publique.
- [ ] `lint-imports` passe : le contrat **D1** est vérifiable (même si les autres
      packages sont vides).
- [ ] Tous les DTO sont `frozen=True`.
- [ ] Toutes les énumérations sont des `StrEnum`.
- [ ] `grep -rn "datetime.now()" src/` ne renvoie **rien** hors `clock.py`.
- [ ] `grep -rn "float(" src/jobtracker/core/money.py` ne renvoie rien.
- [ ] Les pragmas SQLite sont posés au seul endroit prévu.
- [ ] `configs/geo.yaml` couvre au minimum les 40 villes financières du périmètre
      et les quatre pièges d'homonymie du §2.
