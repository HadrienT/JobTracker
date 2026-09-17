# 10 — La cible : quant developer junior, mobile à l'international

> Prérequis : [00-PRIMER.md](00-PRIMER.md).
> À lire si vous touchez `match/`, `configs/profile.yaml`, ou les filtres du front.
>
> Ce fichier joue pour JobTracker le rôle que `10-HARDWARE-TARGET.md` joue pour
> RamTracker : **il décrit ce qu'on cherche, assez précisément pour que le code
> puisse le décider.** Sans lui, le scoring est un avis ; avec lui, c'est une
> spécification.

---

## 1. Le profil

| Axe | Valeur |
|---|---|
| Rôle | **Quant developer** — l'ingénierie du pricing, du risque, de l'exécution, de la donnée de marché |
| Expérience | **0 à 2 ans**. Graduate programmes, junior, et internships convertibles |
| Formation | Profil ingénieur / quant, **non-PhD** |
| Stack | C++ moderne d'abord, Python ensuite ; Rust, CUDA, kdb+/q, OCaml en bonus |
| Mobilité | **Totale.** Europe, Amérique du Nord, Asie, remote. Relocation acceptée |
| Langues | Français natif, anglais professionnel |

La mobilité totale est ce qui rend ce projet différent d'un filtre LinkedIn : le
périmètre est mondial, donc le volume brut est ingérable à la main, donc il faut
un système. Et elle fait du **visa** le premier critère de recevabilité.

---

## 2. Taxonomie des rôles

Ce que `normalize.classify_role` doit produire, et ce que `match` en fait.

| `RoleFamily` | Ce que c'est | Décision |
|---|---|---|
| `quant_dev` | « Quantitative Developer », « Quant Software Engineer », « Core Developer » sur une desk, « Trading Systems Engineer » | **La cible.** Score plein |
| `quant_research` | « Quantitative Researcher », « Quantitative Analyst » | Recevable **si non-PhD** ; pénalisé si le doctorat est exigé |
| `quant_trading` | « Trader », « Junior Trader », « Trading Analyst » | Score faible : ce n'est pas le métier visé, mais les graduate programmes mélangent souvent les deux |
| `swe_platform` | « Software Engineer » chez une société de finance, sans mention quant | **Recevable et important.** Chez un Jane Street ou un Optiver, c'est souvent le même poste sous un autre nom |
| `data_eng` | « Data Engineer », « Market Data Engineer » | Score faible, gardé |
| `risk` | « Risk Analyst », « Model Validation » | Score faible, gardé |
| `other` | Ventes, conformité, RH, juridique, opérations | **Rejeté**, mais **stocké** — le compte d'`other` par société est la mesure du bruit de la source |

**Pourquoi `swe_platform` n'est pas rejeté.** C'est le piège de conception le
plus évident du projet : filtrer sur le mot « quant » dans le titre élimine la
moitié du marché réel. Jane Street, Citadel Securities, Optiver et Hudson River
Trading recrutent des « Software Engineer » qui font exactement le métier visé.
Le discriminant n'est pas le titre, c'est **le secteur de la société** — et il
est dans le registre, pas dans l'annonce. D'où le poids `sector_tier1`.

**Pourquoi `other` est stocké au lieu d'être jeté.** Une source qui remonte
soudainement 95 % d'`other` n'est pas devenue inutile : elle est probablement
cassée, ou son filtre de requête a sauté. Le compte d'`other` est un signal de
santé (P3), et il est gratuit à garder.

---

## 3. Séniorité — la lecture qui compte

Le titre ment, la description tranche. Ordre de résolution :

1. **Années explicites** dans la description : `"3+ years"`, `"minimum 5 years"`,
   `"2-4 years of experience"` → `min_years`.
2. **Marqueurs de programme** : `"graduate programme"`, `"new grad"`, `"campus
   hire"`, `"class of 2026"`, `"Analyst Program"` → `Seniority.GRADUATE`.
3. **Marqueurs de titre** : `Junior`, `Senior`, `Lead`, `Principal`, `Staff`,
   `VP`, `Director`, `Head of`.
4. Rien de tout ça → `Seniority.UNKNOWN`, et **`min_years = None`**.

| Constat | Décision |
|---|---|
| `min_years ≤ 3` ou séniorité `graduate`/`junior`/`intern` | recevable, score plein |
| `min_years` entre 4 et 5 | `stretch` — pas rejeté, mais pénalisé |
| `min_years > 5`, ou `senior`/`lead`/`principal`/`vp` dans le titre | **rejet dur** `senior_only` |
| `UNKNOWN` | **recevable.** Une offre qui ne dit rien est souvent ouverte |

`UNKNOWN` est traité comme recevable pour la même raison que `visa=unknown` : le
silence n'est pas un refus, et rejeter sur le silence supprime des opportunités
sans jamais laisser de trace.

**Le cas `3+ years`.** C'est la formulation la plus fréquente du marché, et la
plus molle : en pratique un profil de deux ans avec la bonne stack passe. Le
seuil de `configs/profile.yaml` est `accept_if_years_max: 3`, délibérément
inclusif.

---

## 4. Visa et droit de travailler — le critère de recevabilité

Rappel du principe P4 : trois états, jamais deux. Ce que le normaliseur doit
reconnaître :

| Formulation | Statut |
|---|---|
| « visa sponsorship available », « we sponsor », « relocation support provided », « we welcome international applicants » | `sponsors` |
| « must have the right to work in X », « no sponsorship is available », « US citizens or permanent residents only », « ITAR » | `no` |
| rien | `unknown` — **le cas majoritaire** |

Réalités de marché à connaître, parce qu'elles expliquent pourquoi ce champ vaut
le coup :

| Zone | Réalité pour un junior français |
|---|---|
| **UE / EEE / Suisse** | Pas de visa en UE. La Suisse demande un permis mais les sociétés de Zoug/Genève le traitent en routine |
| **Royaume-Uni** | Skilled Worker visa. Les grandes maisons de la City sont sponsors licenciés ; c'est la destination la plus accessible hors UE |
| **États-Unis** | H-1B à la loterie, O-1 rare. **La plupart des prop shops ne sponsorisent pas un junior.** Beaucoup l'écrivent explicitement — d'où l'importance de détecter `no` |
| **Singapour** | Employment Pass, seuil de salaire, quotas. Réaliste pour un rôle quant |
| **Hong Kong** | Visa d'emploi relativement ouvert pour la finance |
| Remote | Souvent restreint à un pays ou à un fuseau. La mention de restriction est à extraire comme un `no` déguisé |

Le filtre **par défaut du front** est `{sponsors, unknown}` : il n'exclut que les
`no` explicites. C'est le seul réglage qui n'écarte rien par erreur de parsing.

---

## 5. Saisonnalité — ce qu'un flux générique rate

Le recrutement junior en finance est **calendaire**, pas continu. Un flux qui ne
le montre pas fait rater des campagnes entières.

| Fenêtre | Ce qui s'ouvre |
|---|---|
| **août → novembre** | Campagnes graduate et internships de l'année suivante. Les prop shops ouvrent tôt et ferment vite |
| **janvier → mars** | Seconde vague, rattrapage, postes off-cycle |
| **avril → juillet** | Creux relatif ; surtout du recrutement expérimenté |

Conséquences pour l'implémentation :

1. **`closes_at` est un champ de premier ordre.** Quand l'annonce donne une date
   limite, on l'extrait, on l'affiche, et on peut trier dessus. Une offre qui
   ferme dans six jours est plus urgente qu'une offre au score supérieur qui
   reste ouverte trois mois.
2. **La fraîcheur pèse dans le score** (`freshness_7d`), et une offre de plus de
   `stale_after_days` est rejetée en `stale` — les boards graduate laissent
   traîner des annonces mortes pendant des mois.
3. Le front affiche l'âge **et** la date de clôture dans la ligne, pas dans le
   détail. Voir [12-WEB-UI.md](12-WEB-UI.md) §3.

---

## 6. Grille de scoring

Le score est la **somme de contributions tracées**. Chaque contribution produit
un `Reason(code, delta, evidence)` affiché dans le détail de l'offre : on doit
toujours pouvoir répondre à « pourquoi cette offre est-elle à 78 ? ».

| Contribution | Poids indicatif | Déclencheur |
|---|---|---|
| `title_strong` | +35 | titre dans `profile.titles.strong` |
| `title_possible` | +18 | titre dans `profile.titles.possible` |
| `sector_tier1` | +12 | société de rang 1 du registre (prop shop, market maker, top hedge fund) |
| `seniority_match` | +20 | `graduate` / `junior` / `intern`, ou `min_years ≤ 3` |
| `graduate_programme` | +10 | marqueur de campagne graduate |
| `tech_cpp` | +10 | C++ dans la stack |
| `tech_niche` | +8 | kdb/q, OCaml, Rust, CUDA, FPGA |
| `tech_python` | +6 | |
| `visa_sponsors` | +8 | sponsorship explicite |
| `freshness_7d` | +6 | publiée dans les 7 jours |
| `salary_disclosed` | +3 | une fourchette est annoncée |
| `visa_no` | **−25** | sponsorship explicitement exclu |
| `stale_penalty` | −10 | plus vieille que la moitié de `stale_after_days` |

**Rejets durs** (score non calculé, `tier = rejected`, motif persisté) :

| Motif | Condition |
|---|---|
| `not_quant` | `role_family = other` |
| `senior_only` | `min_years > 4`, ou titre `senior`/`lead`/`principal`/`vp`/`head` |
| `phd_required` | doctorat exigé et non « ou expérience équivalente » |
| `stale` | plus vieille que `stale_after_days` |
| `excluded_title` | titre dans `profile.titles.excluded` |

**Paliers** : `strong ≥ 70`, `possible ≥ 45`, `stretch ≥ 25`, sinon `rejected`.
Tous ces nombres vivent dans `configs/profile.yaml` — aucun n'a le droit
d'apparaître dans le code (interdit n°1).

---

## 7. Ce que le scoring déterministe ne saura pas faire

Et qui part donc au LLM (WP12) :

| Cas | Pourquoi les règles échouent |
|---|---|
| « Software Engineer » chez un hedge fund | Le titre ne dit rien ; il faut lire la description pour savoir si c'est du pricing ou du site web corporate |
| « Quantitative Researcher » | Ouvert aux masters, ou PhD-only sans que le mot « PhD » apparaisse ? |
| Description dans une langue autre que l'anglais ou le français | Les regex de séniorité et de visa n'attrapent rien |
| Offre parapluie : « Graduate Opportunities 2026 » couvrant huit métiers | Un seul titre, huit rôles derrière |
| Séniorité contradictoire : « Junior » dans le titre, « 5+ years » dans le corps | Il faut arbitrer, pas appliquer une priorité fixe |

Le LLM répond à **une question fermée à la fois**, avec un schéma contraint. Il
ne « re-score » jamais l'offre : il fournit les champs que les règles n'ont pas
su remplir, et le score déterministe est recalculé avec. C'est ce qui garde le
scoring reproductible.
