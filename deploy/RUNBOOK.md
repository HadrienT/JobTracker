# Runbook — JobTracker auto-hébergé (WP15)

JobTracker tourne sur le **serveur perso**, comme `quant-modeling`, et n'est joignable
de l'extérieur que par un **tunnel Cloudflare sortant** : aucun port n'est ouvert sur
la box.

```
Navigateur ─HTTPS→ Cloudflare (+ Access) ─tunnel sortant→ cloudflared ─→ web (nginx :8080)
                                                                           ├─ /        build Vite + /config.js
                                                                           └─ /api/ ─→ api (uvicorn :8100)
collector (jobtracker loop) ── seul écrivain ──→ volume jt_data : jobtracker.db (SQLite, WAL)
        └── llama-server (127.0.0.1:8000 de l'hôte, partagé avec OpenHands)
```

| Service | Rôle | Note |
|---|---|---|
| `migrate` | applique le schéma **une fois**, avant tout le reste | évite que collecteur et API migrent en même temps |
| `collector` | `jobtracker loop` | l'**unique écrivain**. `network_mode: host` : c'est le seul moyen d'atteindre le `llama-server` de l'hôte (il écoute sur `127.0.0.1`). Il ne publie aucun port |
| `api` | uvicorn | lecture + `user_flags` (favoris, masquage) |
| `web` | nginx | sert le build, génère `/config.js`, proxifie `/api/` (même origine : pas de CORS) |
| `cloudflared` | tunnel | profil `tunnel` : démarré seulement si `CLOUDFLARE_TUNNEL_TOKEN` est renseigné |

**Ports hôte** (liés à `127.0.0.1`, paramétrables) : `JT_WEB_PORT` (défaut **5190**) et
`JT_API_PORT` (défaut **8100**). La machine porte déjà `quant-modeling` sur **8091** :
aucune collision. Le tunnel n'utilise pas ces ports (il joint `web` par le réseau compose).

**La base ne doit jamais être sur un montage réseau** : SQLite en WAL sur NFS corrompt
en silence. Elle vit dans le volume nommé `jt_data`.

---

## Protection d'accès — décision

L'outil est mono-utilisateur et **sans authentification applicative** (ADR-011). La
protection est donc au niveau du tunnel, et ce n'est pas optionnel :

> **Décision : Cloudflare Access est obligatoire avant d'activer le tunnel.**
> Une application Zero Trust *Self-hosted* sur le hostname, avec une seule règle
> *Allow* : l'e-mail du propriétaire (One-time PIN, ou le fournisseur d'identité déjà
> utilisé pour `quant-modeling`).

Pourquoi pas « un hostname non deviné » : il finit dans les journaux de certificats
publics (Certificate Transparency) et il est scanné en quelques heures. Une URL cachée
n'est pas un contrôle d'accès, et derrière elle `POST /api/postings/{id}/favorite` et
`/hide` écrivent dans la base. Exposer les offres serait peu grave ; laisser n'importe qui
écrire dans `user_flags` ne l'est pas.

Access authentifie à l'edge : nginx et l'API ne voient que des requêtes déjà
authentifiées. Si Access est un jour retiré, retirer aussi le tunnel.

---

## 1. Première installation (de zéro au flux visible)

```bash
git clone https://github.com/HadrienT/JobTracker.git && cd JobTracker
cp .env.example .env
$EDITOR .env          # voir ci-dessous
./scripts/deploy.sh   # build + up + attente que le front et l'API répondent
```

Dans `.env` : `JT_USER_AGENT` (mets un contact réel), `JT_LLM_ENABLED=true` si le
`llama-server` est levé (sinon tout reste déterministe), `JT_ADZUNA_APP_ID/KEY` si tu
veux Adzuna, `JT_AGGREGATORS_ENABLED` (laisser `false` tant que WP13 n'est pas évalué).

Le flux est visible sur `http://127.0.0.1:5190` dès la fin du premier cycle du
collecteur (quelques minutes : la gigue entre requêtes est volontaire).

**Le tunnel** (une fois) :
1. Cloudflare Zero Trust → *Networks → Tunnels* → créer un tunnel, copier le **token**.
2. *Public hostnames* : `jobs.<ton-domaine>` → service `http://web:8080`.
3. **Créer l'application Access** (voir « Protection d'accès ») **avant** l'étape 4.
4. Mettre `CLOUDFLARE_TUNNEL_TOKEN=…` dans `.env`, puis `./scripts/deploy.sh`.

**Au démarrage de la machine** : `sudo cp deploy/jobtracker.service /etc/systemd/system/`
puis `sudo systemctl enable --now jobtracker.service`. **Sauvegardes quotidiennes** :
`deploy/jobtracker-backup.{service,timer}` (même procédure, voir §5).

---

## 2. Mise à jour

```bash
cd ~/JobTracker && git pull --ff-only
./scripts/deploy.sh      # rebuild (cache), migrations, redémarrage, vérification
```

Les migrations sont appliquées par le service `migrate` avant tout le reste. Une
migration qui échoue **empêche le démarrage** (« on ne sert pas un schéma incertain ») :
`docker compose -f docker-compose.prod.yml logs migrate`.

Faire une sauvegarde juste avant : `./scripts/backup.sh`.

---

## 3. « Le flux est périmé »

Le front affiche un bandeau quand `GET /health` dit `feed.stale`.

1. `docker compose -f docker-compose.prod.yml ps` — le collecteur tourne-t-il ?
2. `curl -s http://127.0.0.1:5190/api/health | jq '.feed, .alerts'` — quelle alerte ?
   (`feed_stale`, `source_stalled`, `source_mute`, `volume_drop`).
3. `docker compose -f docker-compose.prod.yml exec collector jobtracker status` — code
   retour 1 = dégradé, avec le détail par source.
4. `docker compose -f docker-compose.prod.yml logs --tail 100 collector` : chercher
   `collect_source_blocked` (disjoncteur ouvert : **ne pas relancer en boucle**, il se
   referme seul avec un délai exponentiel, plafonné à 1 h) ou une exception.

---

## 4. « Une source est muette »

Un jeton d'ATS cassé ne lève pas d'erreur : il renvoie zéro offre (P3).

1. Le rapport hebdomadaire liste nominativement les **sociétés à zéro offre depuis
   30 jours** : `just report`, section 3.
2. Vérifier le jeton : `uv run python tools/probe_ats.py --name "<Société>" --guess <slug>`.
3. Corriger `configs/companies.yaml` (relu en diff), `git pull` + `./scripts/deploy.sh`.
4. Une source entière muette : `jobtracker status` puis les logs du collecteur.

---

## 5. Sauvegardes et restauration

| Quoi | Comment | Fréquence |
|---|---|---|
| `jobtracker.db` | `./scripts/backup.sh` → API de sauvegarde SQLite (**jamais `cp`** sur une base WAL) | quotidienne (timer systemd, 03:30) |
| `configs/` | dans git | à chaque commit |
| Rétention | 30 jours glissants (volume `jt_backups` et `JT_BACKUP_DIR`) | |

Chaque sauvegarde est vérifiée (`PRAGMA integrity_check`) juste après écriture ; une
sauvegarde qui échoue est supprimée, pas gardée comme fausse assurance. Elle est faite
**à chaud** : elle est cohérente pendant un cycle de collecte.

**Mettre `JT_BACKUP_DIR` sur un support hors de la machine** (NAS, USB, cible rclone).
Une sauvegarde sur le même disque que la base survit à une mauvaise migration, pas à un
disque mort.

### Restauration (procédure **testée**)

```bash
./scripts/restore.sh backups/jobtracker-20260918-030000.db
```

Le script : vérifie l'intégrité de la sauvegarde, **arrête** collecteur et API, garde la
base actuelle à côté (`jobtracker.db.pre-restore-<horodatage>`, jamais supprimée),
supprime les `-wal`/`-shm` obsolètes, copie la sauvegarde, redémarre la stack.

**Test effectué le 2026-09-18** sur la stack réelle : sauvegarde à chaud pendant un
cycle de collecte (1 060 offres, `integrity_check = ok`) → base vidée volontairement
(0 offre) → `restore.sh` → 1 060 offres, `integrity_check = ok`, ancienne base
conservée, API servant de nouveau. **Refaire ce test après tout changement de la
procédure** : une sauvegarde jamais restaurée est une hypothèse.

---

## 6. « Le LLM ne répond plus »

Le `llama-server` est partagé avec OpenHands et **n'est pas toujours levé** : c'est
prévu, rien ne casse (ADR-010, pas de repli distant).

1. `curl -s -m 3 http://127.0.0.1:8000/v1/models` (depuis l'hôte) ; `systemctl status llama-server`.
2. Pendant ce temps, les offres ambiguës attendent dans `llm_queue` avec leur verdict
   déterministe ; chaque vidage manqué fait `attempts += 1`. Rien à faire.
3. Le serveur revient : le prochain vidage (toutes les 30 min) résorbe la file, ou
   `docker compose -f docker-compose.prod.yml exec collector jobtracker llm-drain`.
4. La file grossit sans jamais se vider ? `just report`, section 7 (tours sautés) ; vérifier
   `JT_LLM_BASE_URL` : `network_mode: host` du collecteur → `http://127.0.0.1:8000/v1`.

`JT_LLM_ENABLED=false` coupe toute la voie LLM ; le système reste entièrement déterministe.

---

## 7. Rotation des secrets

Un secret ne vit que dans `.env` (jamais dans git, jamais dans un log, jamais dans le
bundle du front : `/config.js` ne contient que l'URL de l'API).

| Secret | Où | Procédure |
|---|---|---|
| `CLOUDFLARE_TUNNEL_TOKEN` | `.env` | Zero Trust → tunnel → *Refresh token* → `.env` → `./scripts/deploy.sh` |
| `JT_ADZUNA_APP_KEY` | `.env` | régénérer chez Adzuna → `.env` → `docker compose -f docker-compose.prod.yml up -d collector` |
| `JT_LINKEDIN_COOKIE` | `.env` | inutilisé (LinkedIn n'est pas collecté, cf. WP13 §7) |

Après une rotation, vérifier qu'aucun secret n'a fui dans les logs :
`docker compose -f docker-compose.prod.yml logs | grep -iE 'app_key|token|cookie'` ne doit rien renvoyer.

---

## Vérifications de santé rapides

```bash
docker compose -f docker-compose.prod.yml ps
curl -sI http://127.0.0.1:5190/ | grep -iE 'content-security|nosniff|referrer|permissions'   # 4 en-têtes
curl -s  http://127.0.0.1:5190/config.js                                                     # apiBase
```

`/config.js` est régénéré à chaque démarrage du conteneur `web` : changer
`JT_PUBLIC_API_BASE` puis `docker compose -f docker-compose.prod.yml up -d web` suffit,
**sans reconstruire l'image**.
