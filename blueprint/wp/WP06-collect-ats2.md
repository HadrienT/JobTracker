# WP06 — `collect` : Workday et les familles restantes

> **Contexte** : WP04 a couvert les ATS faciles, qui portent l'essentiel des prop
> shops et hedge funds. Ce lot ouvre les **banques** — et les banques sont
> presque toutes sous Workday.
>
> Workday coûte cher pour une raison précise : c'est le seul ATS du lot qui
> demande une **reconnaissance manuelle par société**. L'URL contient un `tenant`,
> un numéro d'instance (`wd1`, `wd3`, `wd5`) et un `site`, et aucun des trois ne
> se devine depuis le nom de la banque. Il faut ouvrir la page carrière, regarder
> l'onglet réseau, et noter les trois valeurs dans `extra:`. Compter dix minutes
> par banque, et ne pas essayer d'automatiser ça avant d'en avoir fait dix à la
> main.

**Fichiers à lire** : ce fichier · [11-SOURCES.md](../11-SOURCES.md) §3 ·
[03-INTERFACES.md](../03-INTERFACES.md) §3.1 · [08-TESTING.md](../08-TESTING.md) §3 ·
`collect/http.py` et `collect/base.py` livrés par WP04

**Dépend de** : WP04. **Parallélisable avec** : WP05 · WP07 · WP12.

---

## 1. Objectif

Les collecteurs Workday, SmartRecruiters, Workable, Recruitee, Personio, plus
`custom.py` pour le résidu.

---

## 2. Workday

```text
POST https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
{"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
```

`[À CONFIRMER]` — la forme exacte se vérifie sur une banque du registre.

| Difficulté | Traitement |
|---|---|
| `tenant`, `n`, `site` inconnus | Renseignés à la main dans `extra:` de `companies.yaml`, par reconnaissance |
| Pagination par `offset` | Boucle jusqu'à `total`, **plafonnée par le budget de requêtes** |
| Description absente de la liste | **Second appel** sur le détail de chaque offre |
| `searchText` filtre mal | Ne pas s'en servir comme filtre métier : on collecte tout et on filtre en aval |

**Le second appel par offre est le coût réel de Workday.** Une banque avec 800
offres ouvertes, c'est 800 requêtes de détail. Deux parades, dans cet ordre :

1. **Ne chercher le détail que pour les offres qui passent un premier filtre de
   titre** — la famille de rôle se décide souvent sur le titre seul, et une offre
   « Wealth Management Advisor » n'a pas besoin de sa description.
2. **Cache par `content_hash` du résumé** : une offre déjà connue et inchangée ne
   redemande pas son détail.

Sans ces deux parades, un cycle Workday sur quinze banques dépasse le budget et
remonte `truncated=True` en permanence.

---

## 3. Les familles simples

| Famille | Endpoint `[À CONFIRMER]` | Note |
|---|---|---|
| SmartRecruiters | `GET /v1/companies/{id}/postings?limit=100&offset={n}` | Description sur l'endpoint de détail |
| Workable | `GET /api/v1/widget/accounts/{token}?details=true` | Tout en un appel |
| Recruitee | `GET https://{token}.recruitee.com/api/offers/` | Tout en un appel |
| Personio | `GET https://{token}.jobs.personio.de/xml` | **XML**, pas JSON. Fréquent chez les sociétés allemandes |

Chacune est un parseur de trente lignes qui réutilise `HttpSession`. Aucune ne
justifie une politique HTTP propre.

---

## 4. `custom.py`

Une fonction par société, dans un **seul** fichier, pour celles qui n'ont
réellement aucun ATS connu.

| Règle | Raison |
|---|---|
| Une fonction, un commentaire expliquant pourquoi cette société est là | C'est une dette, elle doit être visible |
| Préférer un JSON embarqué dans le HTML à un parsing de DOM | Le JSON survit à une refonte graphique, pas les sélecteurs CSS |
| Aucun navigateur headless sans avoir essayé `curl_cffi` (interdit n°9) | |
| **Au-delà de 20 entrées, alerte de conception** | Ça signifie qu'une famille d'ATS a été ratée |

---

## 5. Tests attendus

Mêmes cas que WP04 §6, par famille, sur charges utiles figées. En plus :

| Test | Attendu |
|---|---|
| Workday : pagination sur 3 pages | toutes les offres, `requests_made` exact |
| Workday : `total` incohérent avec les pages servies | arrêt propre, log, pas de boucle |
| Workday : budget atteint en plein milieu | `truncated=True`, offres déjà collectées conservées |
| Workday : détail 404 sur une offre | offre conservée sans description, run poursuivi |
| Workday : offre inchangée déjà en base | **aucun appel de détail** |
| Personio : XML malformé | `SourceSchemaChanged` |
| `custom` : refonte simulée du HTML | `SourceSchemaChanged`, pas un silence |

L'avant-dernière ligne est un test de **coût**, pas de correction : c'est lui qui
garantit que le cache du §2 fonctionne réellement.

---

## 6. Critères d'acceptation

- [ ] Les cinq familles sont implémentées et testées en contrat.
- [ ] Workday couvre au moins **10 banques** du registre, avec leurs `extra:` renseignés et vérifiés.
- [ ] Le second appel de détail Workday est **conditionné** par le filtre de titre et le cache de `content_hash`.
- [ ] Aucun collecteur ne construit son propre client HTTP.
- [ ] `custom.py` contient **moins de 20 fonctions**, chacune commentée.
- [ ] Aucun navigateur headless introduit dans ce lot.
- [ ] `just run-once --source workday` collecte réellement sur les banques du registre.
- [ ] `mypy --strict` et `lint-imports` passent.
