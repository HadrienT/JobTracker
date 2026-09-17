# WP03 — `normalize` : la cascade déterministe

> **Contexte** : c'est le composant qu'on améliorera indéfiniment, et le seul dont
> la qualité se **mesure**. Tout le reste marche ou ne marche pas ; le normaliseur,
> lui, a un taux de résolution par étage, qui monte ou qui descend.
>
> Le piège à connaître avant de commencer : **une offre mal normalisée n'a pas
> l'air cassée**. Un « Senior » raté fait apparaître une offre inaccessible en tête
> de flux ; un lieu mal résolu fait disparaître une offre du filtre pays. Dans les
> deux cas l'interface reste parfaitement plausible. C'est pour ça que ce lot se
> développe **contre un corpus figé**, pas contre l'écran.

**Fichiers à lire** : ce fichier · [00-PRIMER.md](../00-PRIMER.md) ·
[09-CONVENTIONS.md](../09-CONVENTIONS.md) §3 · [03-INTERFACES.md](../03-INTERFACES.md) §2.3, §3.2, §3.4 ·
[10-PROFILE-TARGET.md](../10-PROFILE-TARGET.md) §2-4 · [08-TESTING.md](../08-TESTING.md) §2

**Dépend de** : WP01 · WP00 (corpus — mais voir [dependencies.md](../dependencies.md) §5).
**Parallélisable avec** : WP02 · WP04.

---

## 1. Objectif

`normalize(raw: RawPosting, *, taxonomy, geo) -> Posting`, et les neuf étages qui
la composent. **Zéro I/O** (contrat D8). Le `Taxonomy` et le `GeoIndex` arrivent
en argument, chargés par le runtime.

---

## 2. Principe de la cascade

Chaque étage est **pur**, **indépendant** et **testable seul**. Aucun n'a le
droit de lever : un étage qui ne sait pas répond `None` et laisse le champ vide
(invariant **I1**).

```text
title      → titre nettoyé + famille de rôle
location   → tuple[Location, ...]
seniority  → (Seniority, min_years | None)
compensation → Compensation
visa       → (VisaStatus, evidence | None)
techstack  → frozenset[str]
language   → langue de l'annonce, langues exigées
dedup      → fingerprint
```

`resolver_stage` note quel étage a tranché — `rules`, `llm` (WP12) ou
`fallback` — ce qui rend le rejeu ciblé possible.

---

## 3. Les étages qui demandent du soin

### `title.py`

Retirer : codes de requisition (`JR-104882`, `REQ12345`), suffixes de lieu
(`— London`), marqueurs de genre (`(f/h)`, `(m/w/d)`, `H/F`), mentions d'année
(`2026 Start`, `Class of 2026`). **Conserver le titre brut** dans
`title_raw` : le nettoyage est une hypothèse, et on veut pouvoir la réviser.

La famille de rôle se décide sur le titre **et** la description. Le cas
discriminant est celui de [10-PROFILE-TARGET.md](../10-PROFILE-TARGET.md) §2 :
un « Software Engineer » chez un prop shop est `swe_platform`, pas `other`.
Le secteur vient du registre, pas de l'annonce.

### `location.py`

Le cas simple (« London, UK ») est rare. Le cas réel :

| Entrée | Attendu |
|---|---|
| `"New York, NY, United States"` | `city="New York", country="US"` |
| `"London or New York or Hong Kong"` | **trois** `Location` |
| `"Amsterdam (Hybrid – 3 days in office)"` | `city="Amsterdam", remote_mode=HYBRID` |
| `"Remote - EMEA"` | `city=None, region="emea", remote_mode=REMOTE` |
| `"Remote (US only)"` | `remote_mode=REMOTE, country="US"` — **la restriction compte** |
| `"Multiple locations"` | `city=None`, `raw` conservé, **rien d'inventé** |
| `"Cambridge"` | désambiguïsation par `hq_country`, choix journalisé |

`raw` est **toujours** conservé. Le parsing de lieu sera toujours faux quelque
part, et l'UI doit pouvoir afficher la chaîne d'origine au survol.

### `seniority.py`

Ordre de résolution strict, décrit en
[10-PROFILE-TARGET.md](../10-PROFILE-TARGET.md) §3 : années explicites →
marqueurs de programme → marqueurs de titre → `UNKNOWN`.

Cas de contradiction à traiter explicitement : « Junior Developer » dans le titre
et « 5+ years of experience » dans le corps. **La description l'emporte** — le
titre est du marketing de recrutement, la description est ce que le recruteur
filtrera. On journalise la contradiction : c'est un candidat pour le LLM (WP12).

Formulations à couvrir : `3+ years`, `minimum of 3 years`, `at least 3 years`,
`2-4 years`, `3-5 ans d'expérience`, `mindestens 3 Jahre`.

### `compensation.py`

| Entrée | Attendu |
|---|---|
| `"£65,000 - £85,000"` | `65000`–`85000` GBP, `period=YEAR` |
| `"$150K–$250K + bonus"` | `150000`–`250000` USD, `bonus_mentioned=True` |
| `"€4.500 per month"` | `4500` EUR, `period=MONTH` |
| `"Competitive"` | tout à `None`, `raw="Competitive"` |
| `"up to £90,000"` | `min=None`, `max=90000` |

**`Decimal` de bout en bout**, jamais `float`. La période est obligatoire dès
qu'un montant est présent : un `4500` sans période est indistinguable entre un
salaire mensuel néerlandais et une plaisanterie.

**Aucune conversion de devise** (interdit n°5).

### `visa.py`

Le plus rentable du lot, parce qu'il décide de la recevabilité
([00-PRIMER.md](../00-PRIMER.md) §2 P4). L'étage retourne **le statut et
l'extrait de texte qui le justifie** — l'extrait est affiché au survol dans l'UI,
ce qui permet de vérifier d'un coup d'œil si le parseur a raison.

Formulations en [10-PROFILE-TARGET.md](../10-PROFILE-TARGET.md) §4. Les deux
pièges :

- **La double négation** : « we are unable to provide sponsorship at this time »
  est un `no`, pas un `sponsors` parce que le mot « sponsorship » apparaît.
- **La restriction déguisée** : « Remote (US only) », « candidates must be based
  in the EU » n'emploie pas le mot visa mais dit la même chose.

Dans le doute : `UNKNOWN`. Ne jamais inventer un `sponsors`.

### `techstack.py`

Alias depuis `configs/taxonomy.yaml` : `c++`, `cpp`, `c/c++`, `modern c++`,
`C++20` → `cpp`. Les faux positifs à éviter : « R » dans une phrase, « Go » comme
verbe, « C » isolé. Un mot d'une lettre n'est reconnu que délimité et dans un
contexte de liste technique.

### `dedup.py`

Applique `fingerprint` de [03-INTERFACES.md](../03-INTERFACES.md) §3.4. C'est ce
module qui rend WP13 possible : sans lui, allumer LinkedIn triple la taille
apparente du flux.

---

## 4. Tests attendus

| Test | Attendu |
|---|---|
| **I1** : `hypothesis` sur du texte quelconque | aucune exception, jamais |
| **I2** : corpus passé deux fois, horloge figée | résultats identiques |
| Corpus doré complet | taux de résolution par étage affiché, aucune régression |
| Titre `"Senior"` + corps `"0-2 years"` | contradiction journalisée, description prioritaire |
| `"we are unable to provide sponsorship"` | `VisaStatus.NO` |
| `"Remote (US only)"` | `remote_mode=REMOTE`, `country="US"` |
| `"Competitive"` | `Compensation` vide, `raw` conservé |
| `"London or New York"` | deux `Location` |
| Annonce en français / néerlandais / allemand | séniorité et visa extraits |
| `"Software Engineer"` chez un prop shop | `swe_platform`, **pas** `other` |
| Titre avec `(f/h)` et `2026 start` | même empreinte que sans |
| Texte vide, texte de 200 ko, texte binaire | `Posting` valide, champs vides |

---

## 5. Critères d'acceptation

- [ ] Les neuf étages existent avec les signatures de [03-INTERFACES.md](../03-INTERFACES.md) §3.2.
- [ ] Les invariants **I1** et **I2** sont couverts, dont I1 par `hypothesis`.
- [ ] `just test-golden` affiche le tableau de résolution par étage.
- [ ] Taux de résolution minimal à la livraison : **titre 95 %, lieu 85 %,
      séniorité 75 %, visa 60 %**. La rémunération n'a pas de plancher — beaucoup
      d'annonces n'en portent pas.
- [ ] `lint-imports` : contrat **D3** vert, et **aucun import réseau** dans le package.
- [ ] Aucun motif d'extraction métier en dur : ils vivent dans `configs/taxonomy.yaml`.
- [ ] `mypy --strict` passe.
