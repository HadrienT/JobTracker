# Décisions d'architecture (ADR)

> Un ADR par arbitrage structurant : la décision, ce qu'on rejette, et **ce qui
> nous ferait changer d'avis**. Rouvrir un ADR demande un argument nouveau, pas
> une préférence.

---

## ADR-001 — Backend Python 3.13 monolithique, `uv`

**Décision.** Un seul paquet Python, sept sous-packages, deux processus.

**Rejeté.** Full-stack TypeScript (un seul langage, mais l'écosystème de parsing
de texte et de tests de propriété est nettement plus faible) · Go (rapide, mais
on n'a aucun problème de performance : le goulot est le réseau des sources) ·
microservices (aucune contrainte de mise à l'échelle indépendante).

**Ce qui nous ferait changer d'avis.** Rien de prévisible. Le volume est de
l'ordre de 20 000 offres actives.

---

## ADR-002 — SQLite, pas PostgreSQL

**Décision.** Un fichier `jobtracker.db`, journal WAL, FTS5 pour le plein texte.

**Pourquoi.** Le volume attendu est ~16 000 offres actives et ~150 000 lignes
historiques. Un seul écrivain, des lectures ponctuelles. SQLite fait ça sans
service à administrer, sans sauvegarde à orchestrer, et le fichier se copie.
FTS5 couvre le besoin de recherche.

**Rejeté.** PostgreSQL + pgvector (utile si on faisait du classement sémantique
par embeddings — on n'en fait pas, voir ADR-006 ; et ça ajoute un service à
maintenir sur une machine qui en porte déjà plusieurs) · DuckDB (excellent en
analytique, mais on fait du transactionnel ponctuel).

**Ce qui nous ferait changer d'avis.** Un second écrivain concurrent, ou un
besoin de recherche sémantique vectorielle à grande échelle.

---

## ADR-003 — Un collecteur par famille d'ATS, jamais par entreprise

**Décision.** Le code connaît des **familles** (Greenhouse, Lever, Workday…). Les
entreprises vivent en configuration.

**Pourquoi.** Dix collecteurs couvrent quatre cents sociétés. Ajouter une société
devient une ligne de YAML relue en diff, pas un module Python à tester.

**Rejeté.** Un module par société (ingérable à 400) · un scraper générique
piloté par sélecteurs CSS en configuration (on réinvente un langage, et il casse
sur le premier site qui charge en XHR).

**Exception assumée.** `collect/ats/custom.py`, une fonction par société sans ATS
connu. Au-delà de ~20 entrées, c'est le signe qu'on a raté une famille.

---

## ADR-004 — L'enregistrement ATS est canonique, l'agrégateur est un alias

**Décision.** Quand la même offre arrive de plusieurs sources, l'ATS gagne la
place canonique ; les autres deviennent des lignes de `posting_aliases`.

**Pourquoi.** L'ATS porte l'URL de candidature réelle, le titre exact et la
description complète. Un agrégateur porte une version tronquée, une date
d'indexation et un lien de redirection.

**Rejeté.** Garder toutes les copies et dédoublonner à l'affichage (le compte de
facettes devient faux, et le tri par score affiche six fois la même offre) ·
préférer la source la plus récente (un agrégateur réindexe en permanence et
prendrait toujours la main).

---

## ADR-005 — Types du front générés depuis l'OpenAPI

**Décision.** `web/openapi.json` et `web/src/api/schema.gen.ts` sont générés par
`just types`, commités, et un job CI échoue si le diff n'est pas vide.

**Pourquoi.** Des types écrits à la main dérivent silencieusement du serveur dès
qu'un champ change. La dérive se découvre en production, sur une valeur
`undefined`.

**Rejeté.** tRPC (impose TypeScript des deux côtés) · GraphQL (une couche de
complexité pour un client unique) · types manuels (c'est exactement le problème
qu'on évite).

---

## ADR-006 — Scoring déterministe, LLM sur le résidu uniquement

**Décision.** Le score est une somme de contributions tracées, calculée par des
règles testées hors ligne. Le LLM ne remplit que les champs que les règles n'ont
pas su déterminer, et le score est **recalculé** ensuite par les mêmes règles.

**Pourquoi.** Un score reproductible est un score débogable. « Pourquoi cette
offre est-elle à 78 ? » doit avoir une réponse exacte, affichable dans l'UI. Un
score produit par un LLM change d'un run à l'autre et ne se teste pas.

**Rejeté.** Classement par embeddings et similarité au CV (séduisant, mais
opaque : on ne peut ni expliquer ni corriger un rang) · LLM scorant chaque offre
(coût GPU inutile, non reproductible, et le serveur est partagé avec OpenHands).

**Ce qui nous ferait changer d'avis.** Un taux de résolution du normaliseur qui
plafonne bas malgré le corpus doré — auquel cas le LLM prendrait plus de place,
mais toujours comme **remplisseur de champs**, pas comme juge.

---

## ADR-007 — Pagination keyset, jamais `OFFSET`

**Décision.** Curseur opaque construit sur `(clé de tri, posting_id)`.

**Pourquoi.** Avec `OFFSET`, une insertion pendant le scroll décale toutes les
pages suivantes : on saute des offres et on en revoit d'autres. Et le coût de
`OFFSET 10000` croît linéairement.

**Conséquence obligatoire.** Tout tri doit inclure `posting_id` comme second
critère, sinon deux lignes à égalité rendent le curseur ambigu. Voir
[04-DATA-MODEL.md](04-DATA-MODEL.md) §4.

---

## ADR-008 — L'état des filtres vit dans l'URL

**Décision.** Aucun store global pour les filtres, le tri ou la recherche :
`URLSearchParams` est la source de vérité, TanStack Query s'y accroche.

**Pourquoi.** L'écran devient partageable et rechargeable, le bouton Précédent
fonctionne, et un bug de filtre se reproduit en collant une URL.

**Rejeté.** Zustand/Redux (état dupliqué entre l'URL et le store, avec la
synchronisation à maintenir) · état local au composant (perdu au rechargement).

---

## ADR-009 — Le registre d'entreprises est du code source, pas de la donnée

**Décision.** `configs/companies.yaml` est versionné, relu en diff, et
matérialisé en base à chaque démarrage. La base n'en est jamais la source de
vérité.

**Pourquoi.** C'est l'actif principal du projet (P1). En diff, on voit qu'une
société a changé d'ATS, qu'un jeton a été corrigé, qu'une entrée a été
désactivée. En base, tout ça se produit en silence.

---

## ADR-010 — LLM local uniquement, concurrence 1, sans repli distant

**Décision.** `llama-server` sur `127.0.0.1:8000`, partagé avec OpenHands,
concurrence 1, décodage contraint par schéma. **Aucun repli sur une API
distante.**

**Pourquoi.** Contrairement à RamTracker — où une enchère qui se termine dans
deux heures justifie un repli payant — **aucune offre d'emploi n'est urgente à la
minute**. Un tour sauté coûte trente minutes d'attente, c'est-à-dire rien.
Introduire un repli distant ajouterait une clé d'API, un coût variable et un
chemin de code peu testé, pour un gain nul.

**Conséquence.** `classify_llm` retourne `None` quand le serveur est occupé. Ce
n'est pas une erreur, c'est un tour sauté.

---

## ADR-011 — Pas de suivi de candidatures

**Décision.** Le site est un flux consultable, triable, filtrable, avec favoris
et masquage. Ni statut « postulé », ni kanban, ni relances, ni notifications.

**Pourquoi.** Décision explicite du mainteneur au cadrage. Elle a une
conséquence d'architecture qu'il faut respecter : l'API est **en lecture à 95 %**,
la seule table écrite côté serveur est `user_flags`, et le pipeline de collecte
peut réécrire `postings` en permanence sans jamais entrer en conflit.

**Ce qui nous ferait changer d'avis.** Une demande explicite. Si elle vient, elle
se greffe proprement : une table de plus à côté de `user_flags`, sans toucher au
pipeline.

---

## ADR-012 — Les agrégateurs en dernier, derrière un interrupteur

**Décision.** LinkedIn, Indeed, eFC et WTTJ sont implémentés en WP13, isolés dans
`collect/aggregators/`, désactivés par défaut, et **aucun autre lot n'en dépend**.

**Pourquoi.** Trois raisons développées en [11-SOURCES.md](11-SOURCES.md) §5 :
valeur marginale faible (leurs offres doublonnent les ATS), coût de maintenance
permanent (l'anti-bot change plus souvent qu'un schéma d'ATS), et risque
asymétrique (un blocage d'IP touche toute la machine, pas seulement ce projet).

**Le mainteneur a demandé ces sources explicitement** ; elles sont donc
spécifiées et implémentables. La décision porte sur **l'ordre et l'isolement**,
pas sur leur exclusion : on doit pouvoir supprimer le dossier et voir la suite de
tests rester verte.
