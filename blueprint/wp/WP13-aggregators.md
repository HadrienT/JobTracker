# WP13 — Agrégateurs : Adzuna, WTTJ, eFC, LinkedIn, Indeed

> **Contexte** : le mainteneur a explicitement demandé LinkedIn et Indeed. Ce lot
> les spécifie et les implémente. Il les place **en dernier**, **isolés**, et
> **désactivés par défaut** — et ces trois contraintes ne sont pas de la prudence
> gratuite, elles ont des raisons techniques précises, développées en
> [11-SOURCES.md](../11-SOURCES.md) §5 et [decisions.md](../decisions.md) ADR-012.
>
> **Avertissement à lire avant de commencer.** Les CGU de LinkedIn et d'Indeed
> interdisent le scraping automatisé. Leur anti-bot est agressif et évolue en
> permanence. Le blocage éventuel porte sur **l'adresse IP résidentielle de la
> machine**, qui sert aussi à tout le reste. C'est un usage personnel, à faible
> cadence, sur des offres publiques — mais le risque est réel et il n'est pas
> limité à ce projet. Les trois autres sources de ce lot n'ont pas ce problème.

**Fichiers à lire** : ce fichier · [11-SOURCES.md](../11-SOURCES.md) §5-6 ·
[00-PRIMER.md](../00-PRIMER.md) §5 (interdits 7, 8, 9, 14) ·
[03-INTERFACES.md](../03-INTERFACES.md) §3.4 · [decisions.md](../decisions.md) ADR-012

**Dépend de** : WP03 (dédoublonnage **testé**) · WP04 · WP08.
**Parallélisable avec** : WP11 · WP12.

---

## 1. Objectif

Quatre à cinq collecteurs dans `collect/aggregators/`, dans l'ordre de propreté
décroissante, chacun derrière son propre interrupteur.

---

## 2. Le prérequis absolu : le dédoublonnage doit déjà marcher

**Ne pas allumer un agrégateur avant que [03-INTERFACES.md](../03-INTERFACES.md)
§3.4 ne soit implémenté et testé.**

Une offre de hedge fund existe simultanément sur son board Greenhouse, sur
LinkedIn, sur Indeed et sur eFC. Sans dédoublonnage, la première collecte
LinkedIn **triple la taille apparente du flux** et le rend inutilisable : on
scrolle quatre fois la même annonce, et les facettes comptent quatre fois la même
société.

Test de recette de ce lot, avant tout le reste : collecter la même offre depuis
deux sources et vérifier qu'elle apparaît **une** fois, avec un alias.

---

## 3. Ordre d'implémentation

### 3.1 Adzuna — à faire en premier

**API officielle, gratuite avec clé.** C'est la seule voie d'agrégation propre :
pas de CGU à contourner, pas d'anti-bot, un contrat stable. `[À CONFIRMER]` sur
la couverture réelle du secteur finance et sur les quotas.

Si Adzuna couvre bien, une partie de l'intérêt de LinkedIn disparaît — c'est
précisément pourquoi elle est en premier.

### 3.2 Welcome to the Jungle

HTML avec un JSON embarqué dans la page. Bonne couverture France, utile pour les
sociétés françaises sans ATS moderne. Parser le JSON embarqué, **jamais** les
sélecteurs CSS : le JSON survit à une refonte graphique.

### 3.3 eFinancialCareers

Le plus pertinent sectoriellement, mais HTML, structure instable. Cadence basse,
tolérance au `SourceSchemaChanged`.

### 3.4 LinkedIn et Indeed — en dernier

| Contrainte | Mise en œuvre |
|---|---|
| Interrupteur | `JT_AGGREGATORS_ENABLED=true` **et** `sources.yaml: enabled: true`. Double verrou délibéré |
| Cadence | `interval_min: 720` minimum, gigue 20-90 s |
| Impersonation TLS | `curl_cffi` **avant** tout navigateur headless (interdit n°9) |
| Blocage | `SourceBlocked` → disjoncteur ouvert **immédiatement**, repli exponentiel jusqu'à 1 h (interdit n°8) |
| Cookie de session | Dans `.env` uniquement. **Absent = collecteur indisponible**, pas une exception |
| Volume | Requête ciblée sur les mots-clés du profil, jamais un balayage large |
| `robots.txt` | Respecté |

**Le cookie absent ne doit pas planter le run.** Le collecteur se déclare
indisponible et le cycle continue — c'est l'interdit n°14 appliqué : rien ne
dépend de ce lot.

---

## 4. Ce que ces sources apportent réellement

Une offre d'agrégateur qui **doublonne** un ATS déjà collecté n'apporte rien :
elle devient un alias, et l'ATS reste canonique (ADR-004).

La valeur est ailleurs, et elle est réelle mais étroite :

| Apport | Commentaire |
|---|---|
| Sociétés **absentes du registre** | Le vrai gain. Mais la bonne réponse est d'ajouter la société au registre, pas de dépendre de l'agrégateur |
| Offres publiées **uniquement** sur l'agrégateur | Existe, surtout chez les cabinets de recrutement — dont l'intérêt pour la cible est discutable |
| Découverte de nouvelles sociétés | **L'usage le plus intéressant** : extraire les noms d'employeurs inconnus et les proposer pour le registre |

Le dernier point mérite d'être implémenté explicitement : un rapport
« employeurs vus chez les agrégateurs et absents de `companies.yaml` », qui
alimente WP00 en continu. C'est ce qui transforme une source fragile en
contribution durable.

---

## 5. Tests attendus

| Test | Attendu |
|---|---|
| Même offre depuis un ATS et un agrégateur | **une** offre canonique + un alias |
| Même offre depuis trois agrégateurs | une offre, trois alias |
| `JT_AGGREGATORS_ENABLED=false` | aucun appel, aucune erreur, suite de tests verte |
| Cookie absent | collecteur indisponible, run **poursuivi** |
| 429 / challenge | `SourceBlocked`, disjoncteur ouvert, **aucun retry immédiat** |
| Page de challenge servie en 200 | `SourceBlocked`, **pas** un run à zéro |
| Structure HTML modifiée | `SourceSchemaChanged` |
| Gigue | intervalles ≥ minimum configuré, vérifié sur 20 requêtes |
| Employeur inconnu du registre | remonté dans le rapport de découverte |
| `rm -rf collect/aggregators/` | **la suite de tests reste verte** |

L'avant-dernière ligne est le test qui justifie l'existence de ce lot. La
dernière est celle qui prouve son isolement.

---

## 6. Critères d'acceptation

- [ ] Le dédoublonnage est testé **avant** l'activation de toute source de ce lot.
- [ ] Adzuna est implémentée **en premier** et évaluée sur sa couverture réelle.
- [ ] Tout le code de ce lot vit dans `collect/aggregators/`.
- [ ] `rm -rf src/jobtracker/collect/aggregators/` laisse la suite de tests verte.
- [ ] Double verrou d'activation, désactivé par défaut.
- [ ] Une page de challenge servie en 200 est détectée comme `SourceBlocked`,
      **jamais** interprétée comme un board vide.
- [ ] Aucun navigateur headless introduit sans qu'une tentative `curl_cffi` ait
      échoué et soit documentée.
- [ ] Le rapport « employeurs inconnus » est produit et exploitable par WP00.
- [ ] `mypy --strict` et `lint-imports` passent.

---

## 7. État de l'implémentation (2026-09-18) — ce qui a été vérifié, et ce qui ne l'a pas été

Les sondes ont été faites **une requête à la fois, sur l'IP de la machine**, et
seulement là où le risque était négligeable. C'est ce qui explique l'écart entre
la liste du §1 et ce qui existe.

| Source | État | Pourquoi |
|---|---|---|
| **Adzuna** | ✅ implémentée, **jamais exécutée en réel** | Il faut une clé (`JT_ADZUNA_APP_ID/KEY`). Le format vient de la doc publique. Sa couverture finance reste `[À CONFIRMER]` : la juger sur le premier rapport `discover-employers` avant de garder les autres |
| **eFinancialCareers** | ✅ implémentée, **vérifiée en réel** | La page HTML est derrière un **AWS WAF** (405 « Human Verification ») pour un client simple ; mais la page embarque la réponse de sa propre API JSON (`job-search-ui.efinancialcareers.com/v1/efc/jobs/search`), appelable directement, sans `curl_cffi`, sans `robots.txt` sur cet hôte. La fixture est une vraie réponse, anonymisée |
| **Indeed** | ⚠️ implémentée, **jamais vérifiée** | Anti-bot agressif : une sonde ratée risque l'IP. Écrite d'après la structure connue (JSON `mosaic-provider-jobcards`), `curl_cffi`, `robots.txt` vérifié. Échoue **fort** : challenge → `SourceBlocked`, structure inconnue → `SourceSchemaChanged` |
| **WTTJ** | ❌ non implémentée | La page ne contient **aucune offre** (Next.js, résultats chargés côté client via Algolia) : rien à parser, et pas de contrat public stable trouvé sans extraire une clé des bundles JS |
| **LinkedIn** | ❌ non implémentée, **par choix** | Son `robots.txt` interdit `/jobs-guest/`, son seul point d'accès programmatique, et ce lot impose de respecter `robots.txt`. Un collecteur qui ne pourrait jamais tourner serait du code mort |

### Ce que ce lot a ajouté hors de `collect/aggregators/`

| Élément | Pourquoi |
|---|---|
| `companies.discovered` (migration 0004) | `postings.company_slug` est une clé étrangère, et `sync_companies` reconstruit la table à chaque démarrage : un employeur inconnu du registre a besoin d'une ligne à la fois **légale** et **jamais balayée**. Le rapport « employeurs inconnus » (§4) est simplement `WHERE discovered = 1` : `jobtracker discover-employers` |
| `RawPosting.company_name` | Un agrégateur connaît l'employeur par son nom, pas par un slug du registre |
| Résolveur d'employeur | Le dédoublonnage repose sur `company_slug` : « Jane Street Ltd » doit retomber sur `jane_street`, sinon la même offre apparaît deux fois. Correspondance **exacte après normalisation** (un faux rapprochement masque une offre, un rapprochement manqué montre un doublon *et* remonte l'employeur au rapport : la seconde erreur est la moins chère) |
| `AggregatorSetup` dans `collect/base.py` | La seule couture avec `runtime` ; définie hors du dossier supprimable |
| `runtime/aggregator_loader.py` | Atteint le paquet **par chaîne** (`importlib`) : `rm -rf collect/aggregators/` donne « aucun agrégateur ». Contrat `import-linter` **D10** : personne d'autre ne l'importe statiquement |
| `HttpClient` (`collect/http.py`) | `PolicedHttpSession` accepte `httpx.Client` **ou** l'adaptateur `curl_cffi` : la politique (gigue, budget, 403/429) reste écrite une seule fois |

### Verrous

1. `JT_AGGREGATORS_ENABLED=true` (sinon le paquet n'est même pas importé) **et**
2. `enabled: true` par source dans `sources.yaml` (toutes livrées à `false`).

Une clé absente = collecteur **non enregistré**, jamais une exception.
