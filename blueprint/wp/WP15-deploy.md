# WP15 — Déploiement auto-hébergé

> **Contexte** : même cible que `quant-modeling` — le serveur personnel, derrière
> un **tunnel Cloudflare**, sans aucun port ouvert. La machine porte déjà
> plusieurs projets et un `llama-server` qui mange de la VRAM ; JobTracker doit
> s'y insérer sans rien perturber.
>
> Le piège spécifique à ce lot est le piège Vite : les variables `VITE_*` sont
> **inlinées à la compilation**. Une image de front construite avec une URL d'API
> en dur n'est pas déplaçable, et pousse tôt ou tard à mettre un secret dans le
> bundle. La parade est décidée en [12-WEB-UI.md](../12-WEB-UI.md) §9 et doit être
> respectée dès le premier Dockerfile.

**Fichiers à lire** : ce fichier · [12-WEB-UI.md](../12-WEB-UI.md) §9 ·
[06-CONFIG.md](../06-CONFIG.md) §1 · [01-ARCHITECTURE.md](../01-ARCHITECTURE.md) §3

**Dépend de** : WP08 · WP11. **Parallélisable avec** : WP16.

---

## 1. Objectif

Une stack `docker compose` de production, un runbook, des sauvegardes, et le
tunnel.

---

## 2. Les trois services

| Service | Rôle | Note |
|---|---|---|
| `collector` | `jobtracker loop` | **L'unique écrivain** de la base |
| `api` | `uvicorn` | Lecture + `user_flags` |
| `web` | nginx servant le build Vite | Génère `/config.js` au démarrage |

Volume partagé pour `jobtracker.db`. **Jamais sur un montage réseau** :
SQLite en WAL sur NFS produit des corruptions silencieuses.

Ports hôte paramétrables — `JT_API_PORT` (8100) et `JT_WEB_PORT` (5190) — parce
que plusieurs projets tournent sur la même machine.

---

## 3. Configuration au runtime

L'entrypoint nginx génère `/config.js` depuis l'environnement :

```sh
echo "window.__JT_CONFIG__ = { apiBase: \"${JT_PUBLIC_API_BASE}\" };" > /usr/share/nginx/html/config.js
```

Conséquence : **une seule image de front**, identique en local et en production.
Changer l'URL d'API est un redémarrage de conteneur, pas une reconstruction.

Aucune variable `VITE_*` n'est passée au build. Un test de discipline le vérifie.

---

## 4. Tunnel Cloudflare

Un connecteur `cloudflared` vers le service `web`. **Aucun port ouvert sur le
routeur.**

L'outil est mono-utilisateur et sans authentification applicative (ADR-011) : la
protection est donc **au niveau du tunnel** — Cloudflare Access, ou à défaut un
hostname non deviné et non indexé. Ce point est à trancher explicitement dans le
runbook, pas à laisser implicite : une URL publique sans authentification est une
base d'offres exposée, ce qui est peu grave, mais le `POST /favorite` l'est aussi.

En-têtes de sécurité côté nginx : `Content-Security-Policy`,
`X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`.

---

## 5. Sauvegardes

| Quoi | Comment | Fréquence |
|---|---|---|
| `jobtracker.db` | `sqlite3 .backup` — **jamais** `cp` sur une base en WAL | quotidienne |
| `configs/` | dans git | à chaque commit |
| Rétention des sauvegardes | 30 jours glissants | |

`cp` sur une base WAL active copie un fichier incohérent : le `-wal` n'est pas
pris en compte. `.backup` est la seule méthode correcte, et elle fonctionne
pendant que la base est utilisée.

Une restauration doit être **testée une fois**, et la procédure écrite dans le
runbook. Une sauvegarde jamais restaurée est une hypothèse.

---

## 6. Runbook — `deploy/RUNBOOK.md`

| Section | Contenu |
|---|---|
| Première installation | De zéro au flux visible |
| Mise à jour | `git pull`, migrations, redémarrage, vérification |
| « Le flux est périmé » | Diagnostic par `just status` puis `GET /health` |
| « Une source est muette » | Vérifier le jeton, re-sonder avec `probe_ats.py` |
| « Le LLM ne répond plus » | Vérifier `llama-server`, et que JobTracker dégrade proprement |
| Restauration de sauvegarde | Procédure testée |
| Rotation des secrets | |

---

## 7. Tests attendus

| Test | Attendu |
|---|---|
| `docker compose up` depuis un clone neuf | stack fonctionnelle, migrations appliquées |
| `grep VITE_` dans le Dockerfile du front | **aucun résultat** |
| Changement de `JT_PUBLIC_API_BASE` + redémarrage | prise en compte **sans rebuild** |
| Arrêt du collecteur | l'API continue de servir |
| Arrêt de l'API | le collecteur continue de collecter |
| `sqlite3 .backup` pendant un cycle de collecte | sauvegarde cohérente, restaurable |
| Redémarrage du collecteur | disjoncteurs ouverts **conservés** |
| En-têtes de sécurité | présents sur toutes les réponses du front |

---

## 8. Critères d'acceptation

- [ ] `docker compose -f docker-compose.prod.yml up` fonctionne depuis un clone neuf.
- [ ] **Aucune variable `VITE_*` au build** ; la configuration vient de `/config.js`.
- [ ] Ports hôte paramétrables, aucune collision avec les autres projets de la machine.
- [ ] Le tunnel fonctionne, **aucun port ouvert** sur le routeur.
- [ ] La question de la protection d'accès est tranchée et documentée.
- [ ] Sauvegarde quotidienne par `.backup`, **restauration testée une fois**.
- [ ] `deploy/RUNBOOK.md` couvre les sept sections du §6.
- [ ] En-têtes de sécurité présents.
