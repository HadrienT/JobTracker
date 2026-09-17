# 07 — Erreurs, journalisation, surveillance

> Prérequis : [00-PRIMER.md](00-PRIMER.md) §2 (P3).
> À lire quand vous levez ou attrapez une erreur.

---

## 1. Taxonomie — `core/errors.py`

**Toutes** les exceptions maison du projet vivent dans ce fichier. Aucun package
n'a le droit de définir la sienne.

```text
JobTrackerError
├── ConfigError              # YAML invalide, variable manquante, jeton absent
├── StorageError             # SQLite, migration, contrainte violée
├── CollectError
│   ├── SourceUnavailable    # réseau, 5xx, timeout — transitoire, on réessaiera
│   ├── SourceBlocked        # 403/429, challenge anti-bot, captcha — repli exponentiel OBLIGATOIRE
│   ├── SourceSchemaChanged  # 200 mais la charge utile ne ressemble plus à rien
│   └── BoardNotFound        # 404 sur un jeton — le registre est faux, pas le réseau
├── NormalizeError           # une offre indécodable — jamais fatale pour le run
└── LlmUnavailable           # serveur occupé ou éteint — un tour sauté, pas une panne
```

**`SourceBlocked` vs `SourceUnavailable`** est la distinction qui compte : un
blocage impose un repli exponentiel long et l'ouverture du disjoncteur, une
indisponibilité justifie un retry court. Les confondre transforme un blocage
temporaire en bannissement (interdit n°8 du PRIMER).

**`BoardNotFound` n'est pas une erreur réseau.** C'est une erreur de **registre**,
et elle doit remonter jusqu'à un humain : elle signifie que `companies.yaml`
contient une ligne fausse, et cette ligne produit un silence indiscernable d'une
société qui ne recrute pas.

---

## 2. Contrat de journalisation

`structlog`, sortie JSON. Champs obligatoires sur **tout** événement :

| Champ | Toujours | Contenu |
|---|---|---|
| `event` | ✅ | identifiant `snake_case` stable, jamais une phrase |
| `run_id` | ✅ | ULID du cycle, injecté par contexte |
| `source` | quand applicable | |
| `company_slug` | quand applicable | |
| `duration_ms` | sur toute opération d'I/O | |

Règles :

- **On journalise aux frontières d'un composant**, pas à chaque ligne.
- `event` est un identifiant, pas un message : `source_run_empty`, pas
  `"la source n'a rien remonté"`. Les identifiants se `grep`, les phrases non.
- **Aucun secret, aucune charge utile complète** dans un log. Une URL peut
  contenir un jeton : elle est tronquée.
- Le niveau `WARNING` est réservé à ce qui demande une action humaine à terme.
  Un timeout isolé sur un board est `INFO` — sinon les warnings deviennent du
  bruit et on arrête de les lire.

### Événements normatifs

| `event` | Niveau | Quand |
|---|---|---|
| `run_started` / `run_finished` | INFO | encadrent un cycle |
| `source_run_ok` | INFO | avec `fetched`, `new`, `updated`, `aliased` |
| `source_run_empty` | **WARNING** | zéro offre — l'événement central de P3 |
| `source_blocked` | WARNING | avec le délai de repli appliqué |
| `board_not_found` | **ERROR** | le registre est faux, un humain doit corriger |
| `schema_drift` | **ERROR** | la charge utile ne correspond plus au parseur |
| `posting_aliased` | DEBUG | avec l'empreinte et l'identifiant canonique |
| `normalize_failed` | WARNING | avec `posting_id`, jamais fatal |
| `llm_skipped` | INFO | serveur occupé, tour sauté |
| `breaker_opened` / `breaker_closed` | WARNING / INFO | |
| `watchdog_alert` | **ERROR** | voir §4 |

---

## 3. Politique de traitement

| Situation | Comportement |
|---|---|
| Une offre ne se normalise pas | On journalise, on persiste l'offre brute avec `role_family=other`, **on continue le run** |
| Un board échoue | On journalise, on marque le run `error`, **on passe au board suivant** |
| Une source échoue N fois | Le disjoncteur s'ouvre, la source est sautée jusqu'à expiration |
| Le LLM est indisponible | Verdict déterministe conservé, offre remise en file différée |
| La base est verrouillée | `busy_timeout` puis échec net. **Jamais** de retry infini silencieux |
| Une migration échoue | Le processus **refuse de démarrer**. On ne sert pas un schéma incertain |

La règle générale : **un run ne s'arrête jamais à cause d'une offre ou d'un
board.** Il s'arrête à cause de la base ou de la configuration.

---

## 4. Le chien de garde inversé

Le composant le plus important de l'exploitation, parce qu'il surveille ce qui
**ne se produit pas**.

```text
Pour chaque source active :
    si les N derniers runs ont status="empty"       → watchdog_alert(kind="source_mute")
    si aucun run depuis 3 × son intervalle          → watchdog_alert(kind="source_stalled")
    si last_count chute de plus de 80 % vs médiane  → watchdog_alert(kind="volume_drop")

Globalement :
    si aucune offre nouvelle depuis global_stale_hours → watchdog_alert(kind="feed_stale")
```

`volume_drop` mérite un mot : une source qui passe de 300 à 40 offres n'est pas
vide, donc elle échappe à `source_mute`, mais elle est probablement cassée — un
ATS qui change de pagination sert souvent la première page et s'arrête. Une chute
brutale contre la médiane glissante est le seul signal qui l'attrape.

L'alerte est **visible dans `just status` et dans `GET /health`**, et
`just status` sort avec le **code retour 1** quand l'état est dégradé — c'est ce
qui permet de le brancher sur une supervision sans écrire de code en plus.

---

## 5. `GET /health`

```json
{
  "schema_version": 7,
  "feed": { "active_postings": 15420, "newest_posting_age_h": 2.4, "stale": false },
  "sources": [
    { "source": "greenhouse", "status": "ok",     "last_run_at": "…", "last_count": 412, "boards_ok": 187, "boards_error": 2 },
    { "source": "workday",    "status": "degraded","last_run_at": "…", "last_count": 38,  "alert": "volume_drop" },
    { "source": "linkedin",   "status": "disabled" }
  ],
  "alerts": [ { "kind": "volume_drop", "source": "workday", "since": "…" } ]
}
```

La route renvoie **200 même en état dégradé** — c'est une page d'état, pas une
sonde de liveness. Le front l'affiche dans un bandeau : un flux périmé doit être
visible pendant qu'on scrolle, sinon on lit des offres mortes en croyant que le
marché est calme.
