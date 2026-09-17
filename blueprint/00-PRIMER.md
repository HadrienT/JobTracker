# 00 — PRIMER (à lire par tout agent, sans exception)

> Ce fichier est le **contexte minimal complet**. Durée de lecture : ~5 minutes.
> Après lui, lire [09-CONVENTIONS.md](09-CONVENTIONS.md), puis uniquement les
> fichiers listés en tête de votre work package.

---

## 1. Ce qu'on construit

Un **agent de veille sur le marché de l'emploi quantitatif**. Il collecte en
continu les offres publiées par les sociétés de finance qui recrutent des
développeurs quantitatifs — hedge funds, prop shops, market makers, banques
d'investissement, asset managers, éditeurs de logiciels de marché —, les
normalise en un enregistrement typé, les qualifie contre un profil cible, et les
sert dans un **front web dense** où l'on scrolle, trie et filtre.

Le profil cible est fixé et détaillé en [10-PROFILE-TARGET.md](10-PROFILE-TARGET.md) :

> **Quant developer, 0 à 2 ans d'expérience, mobile à l'international.** Pas de
> contrainte géographique : Paris, Londres, Amsterdam, Zurich, New York,
> Chicago, Hong Kong, Singapour et le remote sont tous recevables. C'est ce qui
> rend le **statut de sponsorship visa** aussi important que le salaire.

On ne construit **pas** un outil de candidature automatique, ni un CRM de
recherche d'emploi. Le système collecte, qualifie, affiche. L'humain lit et
postule lui-même.

---

## 2. Les 5 principes non négociables

### (P1) Le registre d'entreprises est le produit, pas le scraper

Un collecteur Greenhouse fait trente lignes, et il sert **deux cents sociétés
d'un coup**. Le problème difficile n'est pas de parser du JSON : c'est de savoir
*quelles sociétés existent* et *quel ATS chacune utilise*. Ce savoir vit dans
`configs/companies.yaml`, il se construit à la main et par sondes, il s'étend en
permanence, et c'est le seul actif du projet qu'on ne peut pas régénérer en une
heure.

Corollaire pratique : **un collecteur par famille d'ATS, jamais un collecteur
par entreprise**. Dix collecteurs couvrent quatre cents sociétés. Écrire du code
spécifique à une société est un échec de conception, sauf page carrière
réellement maison — et il y en a peu.

### (P2) Le dédoublonnage inter-sources est un problème de premier ordre

La même offre existe simultanément sur le board Greenhouse de la société, sur
LinkedIn, sur Indeed, sur eFinancialCareers et dans deux agrégateurs de plus.
Sans dédoublonnage, le flux est illisible dès la première semaine : on scrolle
six fois la même annonce.

La règle de résolution est fixée : **l'enregistrement ATS est canonique**, parce
qu'il porte l'URL de candidature réelle, le titre exact et la description
complète. L'agrégateur devient un **alias** rattaché à l'offre canonique, jamais
une offre de plus. Détail en [03-INTERFACES.md](03-INTERFACES.md) §3.4.

### (P3) Une panne silencieuse est pire qu'un crash

Un jeton de board qui passe en 404, un ATS qui change de schéma, un anti-bot qui
se met à servir une page de challenge : rien de tout ça ne lève d'exception.
Ça renvoie **zéro offre**, et zéro offre ressemble exactement à « cette société
ne recrute pas en ce moment ».

Tout étage capable de se taire porte un compteur persisté, et **l'absence de
résultat déclenche une alerte technique**. C'est le chien de garde inversé de
[07-ERRORS-AND-LOGGING.md](07-ERRORS-AND-LOGGING.md) §4.

### (P4) Le statut visa est un champ de premier ordre, à trois états

Pour un junior français regardant New York, Londres ou Singapour, « cette
société sponsorise-t-elle ? » décide de la recevabilité de l'offre avant le
salaire, avant la stack, avant tout le reste.

Le champ `visa_sponsorship` a **trois états distincts, jamais deux** :

| Valeur | Sens | Origine typique |
|---|---|---|
| `sponsors` | la société l'écrit explicitement | « visa sponsorship available », « we support relocation » |
| `no` | la société l'exclut explicitement | « must have existing right to work in the US », « no sponsorship provided » |
| `unknown` | **rien n'est dit** | le cas le plus fréquent, et de loin |

**`unknown` n'est pas `no`, et `unknown` n'est pas `sponsors`.** Coalescer l'un
dans l'autre est l'erreur qui coûte le plus cher : vers `no`, on perd de vraies
opportunités sans jamais s'en rendre compte ; vers `sponsors`, on remplit le
flux d'offres mortes. L'UI affiche les trois états différemment, et le filtre par
défaut **n'exclut pas** `unknown`.

### (P5) Le LLM ne trie pas le flux, il tranche le résidu

Le scoring est **déterministe et testable hors ligne**. Le LLM n'intervient que
là où les règles refusent de trancher : un poste intitulé « Software Engineer »
chez un hedge fund est-il un rôle quant ? un « Quantitative Researcher » est-il
ouvert à un profil non-PhD ? Ces questions-là demandent de lire un paragraphe,
pas d'appliquer une regex.

Le serveur d'inférence est **local et partagé avec OpenHands** (`~/AgenticEnv`).
JobTracker s'y greffe en second, **concurrence 1**, appels différables, décodage
contraint par schéma. Le dimensionnement se raisonne en **contention GPU**, pas
en coût. Détail en [wp/WP12-match-llm.md](wp/WP12-match-llm.md).

---

## 3. Ce qu'on ne construit PAS

- **Pas de suivi de candidatures.** Ni kanban, ni statut « postulé », ni relances.
  Décision prise et verrouillée (ADR-011). Le site est un flux avec favoris.
- **Pas de notifications.** Pas de ntfy, pas de mail. On consulte le site.
- Pas de framework de scraping générique. Une dizaine de collecteurs concrets
  derrière une interface de quatre lignes.
- Pas d'ORM, pas de broker de messages, pas de conteneur d'injection de
  dépendances. Un fichier SQLite et un processus.
- Pas de moteur de règles configurable pour le scoring. Du Python typé, testé
  contre un corpus, avec ses **poids** en configuration.
- Pas d'agent LLM. Le LLM est appelé pour une classification structurée, en un
  coup, sans boucle ni outils.
- Pas d'authentification sur le front. C'est un outil mono-utilisateur derrière
  un tunnel Cloudflare privé.
- Pas de candidature automatique. Jamais. C'est le meilleur moyen de se faire
  blacklister par les sociétés qu'on vise.

---

## 4. Décisions verrouillées (ne pas rediscuter)

| Sujet | Décision |
|---|---|
| Langage backend | Python 3.13, typé, `uv` pour les dépendances |
| Base de données | **SQLite**, mode WAL, un fichier, FTS5 pour la recherche plein texte. Pas de PostgreSQL (ADR-002) |
| Processus | **un seul** pour la collecte, **un** pour l'API. Pas de Celery, pas de Redis |
| Client HTTP | `httpx` pour les API propres, `curl_cffi` (impersonation TLS) pour les sources protégées |
| Navigateur headless | **plan B uniquement**, jamais le défaut |
| Validation | `pydantic` v2, DTO `frozen=True`, pour tous les contrats et la configuration |
| Journalisation | `structlog`, sortie JSON, `run_id` partout |
| API | **FastAPI**, lecture seule à 95 %, OpenAPI généré et commité |
| Front | **React 19 + Vite + TypeScript strict + Tailwind v4**, TanStack Query + TanStack Virtual |
| Types du front | **générés** depuis l'OpenAPI, jamais écrits à la main (ADR-005) |
| Pagination | **keyset**, jamais `OFFSET` (ADR-007) |
| Sources n°1 | **familles d'ATS** : Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Workday |
| Sources fragiles | LinkedIn, Indeed, eFC, WTJ — **dernier lot, derrière interrupteur, jamais un prérequis** |
| Inférence LLM | serveur **local** `llama-server` sur `127.0.0.1:8000`, endpoint compatible OpenAI, partagé avec OpenHands |
| Décodage LLM | **contraint par schéma**, jamais du JSON en espérant |
| Concurrence LLM | **1**, côté JobTracker. OpenHands reste prioritaire |
| Argent | `Decimal`, jamais `float`. Devise portée avec le montant, **jamais convertie en base** |
| Horodatages | `datetime` **aware UTC** partout |
| Déploiement | auto-hébergé, `docker compose` + tunnel Cloudflare. Aucun port ouvert |

---

## 5. Interdits absolus

1. **Écrire un poids de scoring ou un seuil en dur dans le code.** Ils vivent
   dans `configs/profile.yaml` et se testent contre le corpus doré.
2. **Masquer une erreur** avec `except: pass`, `|| true` ou un repli silencieux.
   Une source qui échoue doit être visible dans `just status`.
3. **Faire de l'I/O réseau dans `normalize` ou `match`** (hors le sous-module
   `match.llm`). Ces deux packages doivent rester testables hors ligne — c'est
   ce qui rend le corpus doré utile.
4. **Coalescer `visa_sponsorship=unknown` en `no` ou en `sponsors`.** Voir §2 (P4).
5. **Convertir une devise au moment de l'écriture en base.** On stocke
   `(montant, devise, période)`. La conversion est un choix d'affichage, avec un
   taux daté, réversible.
6. **Créer une offre de plus quand une source secondaire republie une offre déjà
   collectée.** Elle devient un alias. Voir §2 (P2).
7. **Paralléliser les requêtes vers une même source.** Une à la fois, avec gigue.
   Un board Greenhouse ne mérite pas d'être martelé.
8. **Réessayer immédiatement après un blocage anti-bot.** Repli exponentiel
   obligatoire. Une boucle de retry serrée transforme un blocage temporaire en
   blocage permanent.
9. **Sortir un navigateur headless avant d'avoir essayé l'impersonation TLS.**
   Sur la plupart des sources, les données sont déjà dans le HTML ou dans un JSON
   embarqué ; le blocage porte sur l'empreinte JA3, pas sur le rendu.
10. **Jeter la charge utile brute d'une offre.** Elle est archivée compressée,
    sans exception : sans elle, aucune amélioration du normaliseur n'est
    mesurable par rejeu.
11. **Utiliser `float` pour de l'argent**, ou `datetime.now()` pour une date.
12. **Deviner une API tierce.** Les points `[À CONFIRMER]` se vérifient dans la
    documentation officielle ou par une sonde réelle, jamais par intuition.
13. **Committer un secret** (clé d'API, cookie de session, jeton) ou le laisser
    apparaître dans un log.
14. **Faire dépendre quoi que ce soit de WP13** (LinkedIn/Indeed). Le système
    doit tourner à sources fragiles désactivées.
15. **Écrire du code de collecte spécifique à une entreprise** quand elle utilise
    un ATS connu. Voir §2 (P1).

---

## 6. Vocabulaire

| Terme | Sens dans ce projet |
|---|---|
| **Source** | Une famille d'ATS ou un agrégateur : `greenhouse`, `lever`, `workday`, `linkedin`… Pas une entreprise. |
| **Board** | L'instance d'un ATS pour une entreprise donnée, identifiée par un **jeton** (`token`/`slug`/`tenant`). |
| **Registre** (`companies.yaml`) | La liste des entreprises suivies, chacune avec sa source, son jeton, son secteur et son rang de priorité. |
| **Offre brute** (`RawPosting`) | Une offre telle que collectée : normalisée en structure, non interprétée. La charge utile d'origine est archivée avec elle. |
| **Offre** (`Posting`) | Le résultat de la normalisation : lieu structuré, séniorité, stack, rémunération, visa, empreinte. |
| **Verdict** (`MatchVerdict`) | Le résultat de la qualification : score, palier, raisons, motif de rejet éventuel. |
| **Palier** (`tier`) | `strong` / `possible` / `stretch` / `rejected`. Ce que l'UI affiche comme pastille. |
| **Empreinte** (`fingerprint`) | La clé de dédoublonnage inter-sources, dérivée de (société, titre normalisé, pays, fenêtre de date). |
| **Alias** | Une republication de la même offre par une autre source, rattachée à l'offre canonique. |
| **Motif de rejet** | Identifiant stable `snake_case`, persisté, jamais traduit : `senior_only`, `phd_required`, `not_quant`, `stale`. |
| **Fraîcheur** | Âge de l'offre. `posted_at` quand la source le donne honnêtement, sinon `first_seen_at`. Voir [09-CONVENTIONS.md](09-CONVENTIONS.md) §3. |
| **Fenêtre de campagne** | Période d'ouverture d'un programme graduate. Un flux qui n'affiche pas « clôture dans 6 jours » est inutile pour du recrutement junior. |
| **Quarantaine** | Offre que ni les règles ni le LLM n'ont tranchée. Ni affichée en `strong`, ni jetée. |
| **Chien de garde inversé** | Alerte déclenchée par l'**absence** de résultats, pas par une erreur. |
| **Voie urgente / différée** | Les deux files d'appel au LLM. L'urgente accepte la contention, la différée l'évite. |

---

## 7. Conventions critiques (détail en [09-CONVENTIONS.md](09-CONVENTIONS.md))

- **Unités explicites, toujours** : `timeout_s`, `window_days`, `salary_min`
  accompagné de `currency` et `period`. Jamais un nombre nu.
- **Argent en `Decimal`**, devise portée à côté, jamais convertie en base.
- **`None` n'est pas `0`, et `unknown` n'est pas `no`.** Vrai pour le salaire,
  vrai pour le visa, vrai pour la date de publication.
- Toute offre écartée porte un **motif de rejet** persisté, pour pouvoir rejouer
  le normaliseur sur l'archive et mesurer le progrès.
- Les identifiants de source, de motif de rejet et de palier sont **stables** :
  ils sont en base, comparés en test et utilisés pour cibler un rejeu. Les
  renommer casse l'historique.

---

## 8. Definition of Done (minimum, pour toute contribution)

- [ ] Signatures typées, `mypy --strict` passe.
- [ ] `ruff check` et `ruff format --check` passent.
- [ ] `import-linter` passe (contrats D1→D9 de [01-ARCHITECTURE.md](01-ARCHITECTURE.md)).
- [ ] Tests unitaires ; pour `normalize` et `match`, non-régression sur le corpus doré.
- [ ] Aucun poids, seuil ou paramètre en dur.
- [ ] Erreurs issues de la taxonomie de [07-ERRORS-AND-LOGGING.md](07-ERRORS-AND-LOGGING.md).
- [ ] Journalisation structurée aux frontières du composant, avec `run_id`.
- [ ] Aucun secret dans le code ni dans les logs.
- [ ] `.env.example` et [06-CONFIG.md](06-CONFIG.md) à jour si un paramètre est ajouté.
- [ ] Si une route ou un schéma d'API change : `just types` relancé, les deux
      fichiers générés commités.
- [ ] Tout point incertain sur une API tierce marqué `[À CONFIRMER]`, jamais deviné.
