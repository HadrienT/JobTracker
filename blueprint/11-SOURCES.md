# 11 — Catalogue des sources

> Prérequis : [00-PRIMER.md](00-PRIMER.md) §2 (P1).
> À lire avant d'écrire un collecteur.
>
> **Tout endpoint de ce fichier est marqué `[À CONFIRMER]`.** Les ATS changent
> d'URL, de pagination et de format sans prévenir. WP00 existe pour les vérifier
> par sonde réelle (`tools/probe_ats.py`), et toute correction est reportée ici
> dans le même commit. Deviner est l'interdit n°12.

---

## 1. Le principe : une famille, pas une entreprise

Une famille d'ATS = **un collecteur de trente lignes qui sert des centaines de
sociétés**. Écrire du code par entreprise est un échec de conception (P1).

```text
1 collecteur Greenhouse  ×  ~200 jetons de board  =  ~200 sociétés couvertes
1 collecteur Workday     ×  ~60 tenants           =  toutes les grandes banques
1 collecteur custom      ×  1 fonction par site   =  le résidu, ~15 sociétés
```

L'ordre d'implémentation suit le rapport couverture/effort : Greenhouse, Lever et
Ashby d'abord (WP04) — JSON propre, sans authentification, sans anti-bot, et ils
couvrent l'essentiel des prop shops et hedge funds. Workday ensuite (WP06), parce
qu'il ouvre les banques d'un coup mais demande un POST paginé.

---

## 2. Familles à endpoint JSON propre — WP04

| Famille | Endpoint `[À CONFIRMER]` | Pagination | Notes |
|---|---|---|---|
| **Greenhouse** | `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | aucune, tout en un appel | `content=true` renvoie la description. Le jeton est le slug visible dans l'URL du board public |
| **Lever** | `GET https://api.lever.co/v0/postings/{token}?mode=json` | aucune | Champs `categories.location`, `categories.commitment`, `lists` pour les sections |
| **Ashby** | `GET https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true` | aucune | `includeCompensation` donne des fourchettes réelles quand la société les publie |

Ces trois-là sont des **API publiques documentées, destinées à l'agrégation** :
c'est exactement l'usage prévu. Pas d'anti-bot, pas de clé, pas de zone grise.
Cadence raisonnable quand même — une requête toutes les quelques secondes,
intervalle de 3 h par board (`configs/sources.yaml`).

---

## 3. Familles à négocier — WP06

| Famille | Endpoint `[À CONFIRMER]` | Difficulté |
|---|---|---|
| **Workday** | `POST https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs` corps `{"appliedFacets":{},"limit":20,"offset":0,"searchText":""}` | Il faut découvrir `{tenant}`, `{n}` et `{site}` par société. Pagination par `offset`. La description exige un **second appel** sur le détail de l'offre |
| **SmartRecruiters** | `GET https://api.smartrecruiters.com/v1/companies/{id}/postings?limit=100&offset=0` | Simple. Description sur l'endpoint de détail |
| **Workable** | `GET https://apply.workable.com/api/v1/widget/accounts/{token}?details=true` | Simple |
| **Recruitee** | `GET https://{token}.recruitee.com/api/offers/` | Simple |
| **Personio** | `GET https://{token}.jobs.personio.de/xml` | XML, pas JSON. Fréquent chez les sociétés allemandes |
| **Teamtailor / Jobvite / iCIMS / Taleo** | variable | Souvent pas d'API publique ; à traiter comme `custom` ou à abandonner selon le nombre de sociétés concernées |

**Workday mérite un avertissement.** C'est l'ATS de la plupart des grandes
banques, donc il ouvre beaucoup de portes d'un coup, mais : deux appels par
offre, un `searchText` qui filtre mal, et des tenants introuvables sans
inspecter le réseau d'une page carrière. Compter une demi-journée de
reconnaissance rien que pour la banque française moyenne. C'est pourquoi il est
en WP06 et pas en WP04.

**Le collecteur `custom`.** Une fonction par société, dans un seul fichier, pour
les sociétés qui n'ont réellement aucun ATS connu — typiquement les prop shops
qui hébergent leur board eux-mêmes. Chaque fonction y est une dette assumée et
commentée. Au-delà de ~20 entrées, c'est le signe qu'on a raté une famille d'ATS.

---

## 4. Le registre d'amorce

Amorce indicative pour `configs/companies.yaml`. **Les colonnes « source » et
« jeton » ne sont pas renseignées ici volontairement** : c'est précisément le
travail de WP00, par sonde. Cette liste donne les *noms* et le *rang*, pas les
jetons.

### Rang 1 — prop trading, market making

Citadel Securities · Jane Street · Jump Trading · Hudson River Trading · Optiver ·
IMC Trading · Flow Traders · DRW · SIG (Susquehanna) · Tower Research · XTX Markets ·
Old Mission · Akuna Capital · Five Rings · Headlands Technologies · Belvedere ·
Wolverine · Peak6 · Quantlab · Virtu Financial · Maven Securities · Vatic Labs ·
Radix Trading · Grasshopper · TransMarket · Da Vinci · Webb Traders · All Options

### Rang 1 — hedge funds quantitatifs

Two Sigma · D. E. Shaw · Citadel · Millennium · Point72 / Cubist · Balyasny ·
ExodusPoint · Schonfeld · Squarepoint · Qube Research & Technologies · G-Research ·
Man Group / AHL · Marshall Wace · Brevan Howard · Capula · Winton · Aspect Capital ·
**Capital Fund Management (CFM)** · BlueCrest · Verition · Walleye · AQR ·
Bridgewater · Voleon · PDT Partners · Renaissance Technologies

### Rang 2 — banques d'investissement

Goldman Sachs · Morgan Stanley · J.P. Morgan · Bank of America · Citi · Barclays ·
HSBC · **BNP Paribas** · **Société Générale** · **Natixis** · **Crédit Agricole CIB** ·
Deutsche Bank · UBS · Nomura · MUFG · Standard Chartered · Macquarie · RBC ·
Scotiabank · BMO · TD Securities · Jefferies · Mizuho

### Rang 2 — asset managers et assurance

BlackRock · PIMCO · Vanguard · Fidelity · Wellington · **Amundi** · **AXA IM** ·
Robeco · APG · PGGM · Nuveen · Schroders · Legal & General · Allianz GI ·
**Tikehau Capital** · **Ostrum**

### Rang 2 — éditeurs et données de marché

Bloomberg · S&P Global · MSCI · FactSet · ICE · Nasdaq · LSEG · **Murex** ·
Finastra · ION Group · Numerix · Quantifi · OpenGamma · **Kaiko** · Databento ·
**Milliman** · **Kepler Cheuvreux**

### Rang 3 — crypto quantitatif

Jump Crypto · GSR · Wintermute · B2C2 · Amber Group · Keyrock · **Flowdesk** ·
Cumberland · Galaxy Digital

**Méthode d'extension du registre** — c'est ça, le travail durable :

1. Partir d'un annuaire sectoriel ou d'une liste de membres (associations de
   market makers, listes de sociétés agréées).
2. Pour chaque société, ouvrir la page carrière et **regarder l'URL du board** :
   `boards.greenhouse.io/xxx`, `jobs.lever.co/xxx`, `jobs.ashbyhq.com/xxx`,
   `xxx.wd3.myworkdayjobs.com` — la famille et le jeton se lisent directement.
3. Pour les pages qui ne montrent rien, ouvrir l'onglet réseau : l'ATS est
   presque toujours appelé en XHR.
4. `tools/probe_ats.py <slug>` confirme le jeton et capture une charge utile de
   référence pour les tests de contrat.
5. Une société dont la source reste introuvable entre avec `enabled: false` et un
   commentaire. **On ne la supprime pas** : sinon on la re-sonde tous les six
   mois sans le savoir.

---

## 5. Agrégateurs — WP13 uniquement, et jamais un prérequis

| Source | Statut | Ce qu'il faut savoir |
|---|---|---|
| **Adzuna** | ✅ **API officielle, gratuite avec clé** | La seule voie d'agrégation propre. `[À CONFIRMER]` sur la couverture finance. **À tenter en premier** |
| **eFinancialCareers** | ⚠️ HTML | Le plus pertinent pour le secteur, mais scraping HTML, structure instable |
| **Welcome to the Jungle** | ⚠️ HTML/JSON embarqué | Bonne couverture France, utile pour les sociétés françaises sans ATS moderne |
| **LinkedIn** | ❌ CGU + anti-bot | Volume maximal, mais scraping interdit par les CGU, anti-bot agressif, nécessite un cookie de session personnel. Doublonne massivement les ATS |
| **Indeed** | ❌ CGU + anti-bot | Même chose. API partenaire fermée aux nouveaux entrants |

**La règle qui encadre tout ce lot** : ces sources sont derrière
`JT_AGGREGATORS_ENABLED=false` par défaut, isolées dans
`collect/aggregators/`, et **rien d'autre dans le projet n'en dépend**. On doit
pouvoir faire `rm -rf src/jobtracker/collect/aggregators/` et voir la suite de
tests rester verte.

Trois raisons de les traiter en dernier, et pas par excès de prudence :

1. **La valeur marginale est faible.** Une offre LinkedIn d'un hedge fund est
   déjà sur son board Greenhouse, avec une meilleure description et la vraie URL
   de candidature. L'agrégateur n'apporte que les sociétés **absentes du
   registre** — et la bonne réponse à ça est d'étendre le registre.
2. **Le coût de maintenance est permanent.** Un anti-bot change plus souvent
   qu'un schéma d'ATS. Ce lot sera la source n°1 de pannes du projet.
3. **Le risque est asymétrique.** Un blocage d'IP n'affecte pas que JobTracker :
   c'est la même IP résidentielle qui sert à tout le reste.

Si ce lot est fait, il l'est dans cet ordre : **Adzuna** (propre) → **WTTJ** →
**eFC** → LinkedIn/Indeed en dernier, avec cadence très basse, gigue large et
repli exponentiel long. Et le dédoublonnage de [03-INTERFACES.md](03-INTERFACES.md)
§3.4 doit être **déjà en place et testé** avant d'allumer quoi que ce soit : sans
lui, la première collecte LinkedIn triple la taille apparente du flux.

---

## 6. Politique HTTP commune — `collect/http.py`

Valable pour **toutes** les sources, y compris les gentilles.

| Règle | Valeur |
|---|---|
| Concurrence par source | **1**. Jamais de parallélisme sur un même hôte |
| Gigue entre deux requêtes | `configs/sources.yaml`, 2-7 s par défaut |
| `User-Agent` | Honnête et identifiable sur les ATS officiels. L'impersonation TLS (`curl_cffi`) est réservée aux sources qui bloquent |
| Repli sur 429/403 | Exponentiel, base 30 s, plafond 1 h. **Jamais de retry immédiat** (interdit n°8) |
| Budget de requêtes par run | Plafonné par source. Dépassement → `truncated=True`, pas d'exception |
| Timeout | 20 s par défaut |
| `robots.txt` | Respecté sur les sources HTML. Les API publiques d'ATS n'y sont pas soumises |
| Cache conditionnel | `ETag` / `If-Modified-Since` quand la source les sert — gratuit et divise le volume |
