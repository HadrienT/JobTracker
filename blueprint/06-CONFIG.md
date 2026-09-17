# 06 — Configuration

> Prérequis : [00-PRIMER.md](00-PRIMER.md).
> À lire quand vous ajoutez un paramètre. **Ajouter un paramètre sans le
> documenter ici et dans `.env.example` échoue la Definition of Done.**

Deux niveaux, et un seul point d'entrée.

| Niveau | Où | Contient | Versionné |
|---|---|---|---|
| **Secrets et environnement** | `.env` | chemins, ports, jetons d'API, URL du LLM | ❌ (`.env.example` l'est) |
| **Paramètres métier** | `configs/*.yaml` | registre, profil, cadences, taxonomies | ✅ **oui, relus en diff** |

`core.config.Settings` (pydantic-settings) est le **seul** endroit qui lit
`os.environ` ou ouvre un YAML. Partout ailleurs, la configuration arrive en
argument.

---

## 1. `.env`

| Variable | Défaut | Rôle |
|---|---|---|
| `JT_DB_PATH` | `./jobtracker.db` | Fichier SQLite. **Jamais sur un montage réseau** |
| `JT_LOG_LEVEL` | `INFO` | |
| `JT_LOG_FORMAT` | `json` | `console` en développement |
| `JT_API_HOST` / `JT_API_PORT` | `127.0.0.1` / `8100` | Port hôte paramétrable : plusieurs projets sur la même machine |
| `JT_WEB_PORT` | `5190` | Front Vite / nginx |
| `JT_LLM_BASE_URL` | `http://127.0.0.1:8000/v1` | `llama-server`, partagé avec OpenHands |
| `JT_LLM_MODEL` | `Qwen3-Coder-30B-A3B-Instruct` | Doit correspondre à `active:` de `~/AgenticEnv/configs/models.yaml` |
| `JT_LLM_ENABLED` | `false` | WP12 l'active. Le système tourne sans |
| `JT_USER_AGENT` | `JobTracker/0.1 (+contact)` | En-tête honnête. **Ne pas usurper un navigateur sur un ATS officiel** |
| `JT_HTTP_TIMEOUT_S` | `20` | |
| `JT_AGGREGATORS_ENABLED` | `false` | **L'interrupteur de WP13.** Défaut `false`, et il le reste |
| `JT_LINKEDIN_COOKIE` | — | Secret. Si absent, le collecteur LinkedIn se déclare indisponible, il ne plante pas |
| `JT_ADZUNA_APP_ID` / `JT_ADZUNA_APP_KEY` | — | API d'agrégation légale, voir [11-SOURCES.md](11-SOURCES.md) §5 |

Toute variable est préfixée `JT_`. Sans exception — c'est ce qui permet de faire
tourner JobTracker à côté de RamTracker et d'AgenticEnv sans collision.

---

## 2. `configs/companies.yaml` — le registre

**Le fichier le plus important du dépôt** (principe P1).

```yaml
- slug: jane_street              # stable, snake_case, jamais renommé
  name: Jane Street
  source: custom                 # [À CONFIRMER] au WP00 via tools/probe_ats.py
  token: ""
  sector: prop_trading
  hq_country: US
  priority: 1
  enabled: true

- slug: optiver
  name: Optiver
  source: greenhouse             # [À CONFIRMER]
  token: optiver
  sector: market_making
  hq_country: NL
  priority: 1
  enabled: true

- slug: bnp_paribas
  name: BNP Paribas
  source: workday                # [À CONFIRMER]
  token: bnpparibas
  extra: { site: BNP_Paribas_Careers, wd: "3" }
  sector: bank
  hq_country: FR
  priority: 2
  enabled: true
```

| Champ | Règle |
|---|---|
| `slug` | **Jamais renommé.** Il est en base, dans les favoris, dans les URL partagées |
| `source` | Une valeur de `Source`. `custom` uniquement s'il n'existe aucun ATS connu |
| `token` | Le jeton du board. Sa découverte est le travail de WP00 |
| `extra` | Paramètres propres à la famille (site et numéro de tenant Workday, etc.) |
| `priority` | `1` = sondé chaque cycle · `2` = quotidien · `3` = hebdomadaire |
| `enabled` | Un `false` documenté vaut mieux qu'une ligne supprimée : on garde la trace du sondage |

**Toute entrée dont le `token` n'a pas été vérifié par une sonde réelle porte un
commentaire `# [À CONFIRMER]`.** Un jeton deviné qui renvoie 404 est
indiscernable d'une société qui ne recrute pas — c'est exactement le piège P3.

---

## 3. `configs/profile.yaml` — la cible

Voir [10-PROFILE-TARGET.md](10-PROFILE-TARGET.md) pour le sens de chaque poids.

```yaml
version: 1                       # incrémenté à chaque changement : permet de rescorer le périmé

titles:
  strong:   ["quantitative developer", "quant developer", "quantitative software engineer",
             "quant dev", "software engineer, trading", "core developer"]
  possible: ["software engineer", "c++ developer", "python developer", "platform engineer",
             "quantitative researcher", "quantitative analyst"]
  excluded: ["sales", "recruiter", "compliance", "audit", "hr business partner",
             "account manager", "client relationship"]

seniority:
  target: [graduate, junior, intern]
  accept_if_years_max: 3         # "3+ years" reste recevable, "5+" non
  reject: [senior, lead]

hard_rejects:
  phd_required: true             # un doctorat exigé écarte le profil
  min_years_above: 4
  stale_after_days: 60           # une offre de plus de 60 jours est probablement morte

weights:                         # tous les points du score sortent d'ici, AUCUN en dur
  title_strong: 35
  title_possible: 18
  sector_tier1: 12
  tech_cpp: 10
  tech_python: 6
  tech_niche: 8                  # kdb, ocaml, rust, cuda, fpga
  seniority_match: 20
  graduate_programme: 10
  visa_sponsors: 8
  visa_no: -25
  salary_disclosed: 3
  freshness_7d: 6
  stale_penalty: -10

tiers:                           # seuils de palier
  strong: 70
  possible: 45
  stretch: 25
```

---

## 4. `configs/sources.yaml` — cadences et budgets

```yaml
defaults:
  timeout_s: 20
  max_requests_per_run: 200
  jitter_s: [2, 7]               # intervalle aléatoire entre deux requêtes d'une même source
  backoff_base_s: 30
  backoff_max_s: 3600
  dedup_window_days: 14          # compartiment de date de l'empreinte (03-INTERFACES §3.4)

sources:
  greenhouse: { interval_min: 180, enabled: true }
  lever:      { interval_min: 180, enabled: true }
  ashby:      { interval_min: 180, enabled: true }
  workday:    { interval_min: 360, enabled: true, max_requests_per_run: 400 }
  linkedin:   { interval_min: 720, enabled: false, jitter_s: [20, 90] }   # WP13
  indeed:     { interval_min: 720, enabled: false, jitter_s: [20, 90] }   # WP13

watchdog:
  empty_runs_before_alert: 3     # 3 cycles muets d'affilée = alerte
  global_stale_hours: 12         # aucune offre nouvelle depuis 12 h = alerte globale
```

---

## 5. `configs/taxonomy.yaml` et `configs/geo.yaml`

`taxonomy.yaml` porte les motifs d'extraction du normaliseur : familles de rôles,
mots-clés de stack avec leurs alias (`c++`, `cpp`, `c/c++`, `modern c++` → `cpp`),
marqueurs de séniorité, formulations de sponsorship dans les deux sens.

`geo.yaml` porte les alias de villes (`NYC` → `New York`, `SF` → `San Francisco`,
`HK` → `Hong Kong`), la correspondance ville → pays, et les groupements de
régions. Il porte aussi les **pièges connus** : « Cambridge » est au Royaume-Uni
*et* dans le Massachusetts ; « London » est au Royaume-Uni *et* en Ontario. La
désambiguïsation utilise le `hq_country` de la société comme indice, et ce choix
est journalisé.

---

## 6. Règles transverses

| # | Règle |
|---|---|
| **C1** | Aucune valeur de ces fichiers n'apparaît en dur dans le code. Une constante littérale de seuil est un bug |
| **C2** | `Settings` est chargée une fois, au démarrage, et passée en argument. Pas de singleton relu au milieu d'une boucle |
| **C3** | Un YAML invalide **empêche le démarrage** avec un message qui nomme le fichier, la ligne et le champ. Pas de valeur par défaut silencieuse |
| **C4** | `profile.yaml` et `taxonomy.yaml` portent un champ `version` ; le changer déclenche un rescoring au prochain cycle, pas une migration |
| **C5** | Un secret ne vit que dans `.env`, n'apparaît jamais dans un log, et `.env.example` porte une valeur manifestement factice |
