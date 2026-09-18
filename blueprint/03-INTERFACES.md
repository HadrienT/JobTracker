# 03 — Interfaces inter-packages

> Prérequis : [00-PRIMER.md](00-PRIMER.md), [01-ARCHITECTURE.md](01-ARCHITECTURE.md).
> **Signatures et formes de données uniquement. Aucun corps de fonction.**
>
> Ce fichier est le contrat qui permet à plusieurs sessions de coder en
> parallèle : tant que ces signatures sont respectées, deux packages écrits
> séparément se branchent sans négociation. **Le modifier impose de mettre à jour
> [dependencies.md](dependencies.md) §4 et de prévenir les lots concernés par une
> issue GitHub.**

---

## 1. Énumérations — `core/enums.py`

Toutes des `StrEnum`, pour être lisibles en base, en JSON et dans l'URL du front.

```python
class Source(StrEnum):
    GREENHOUSE = "greenhouse"; LEVER = "lever"; ASHBY = "ashby"
    SMARTRECRUITERS = "smartrecruiters"; WORKABLE = "workable"
    RECRUITEE = "recruitee"; PERSONIO = "personio"; WORKDAY = "workday"
    CUSTOM = "custom"
    EFC = "efinancialcareers"; WTTJ = "wttj"; LINKEDIN = "linkedin"; INDEED = "indeed"

class RoleFamily(StrEnum):
    QUANT_DEV = "quant_dev"            # la cible
    QUANT_RESEARCH = "quant_research"  # recevable si non-PhD
    QUANT_TRADING = "quant_trading"
    SWE_PLATFORM = "swe_platform"      # SWE en société de finance : recevable
    DATA_ENG = "data_eng"
    RISK = "risk"
    OTHER = "other"                    # hors périmètre, gardé pour audit

class Seniority(StrEnum):
    INTERN = "intern"; GRADUATE = "graduate"; JUNIOR = "junior"
    MID = "mid"; SENIOR = "senior"; LEAD = "lead"; UNKNOWN = "unknown"

class VisaStatus(StrEnum):
    SPONSORS = "sponsors"; NO = "no"; UNKNOWN = "unknown"   # trois états, P4

class RemoteMode(StrEnum):
    ONSITE = "onsite"; HYBRID = "hybrid"; REMOTE = "remote"; UNKNOWN = "unknown"

class SalaryPeriod(StrEnum):
    YEAR = "year"; MONTH = "month"; DAY = "day"; HOUR = "hour"

class Tier(StrEnum):
    STRONG = "strong"; POSSIBLE = "possible"; STRETCH = "stretch"; REJECTED = "rejected"
```

**Règle de stabilité.** Ces valeurs sont persistées en base, comparées en test et
présentes dans les URL partageables du front. En **ajouter** est libre ; en
**renommer** exige une migration et casse les liens sauvegardés.

---

## 2. DTO — `core/models.py`

Tous `frozen=True`. Un étage produit un nouvel objet, il ne mute jamais son
entrée.

### 2.1 Registre

```python
class Board(BaseModel, frozen=True):
    """Une entrée de configs/companies.yaml, résolue."""
    company_slug: str          # identifiant stable, snake_case : "jane_street"
    company_name: str          # affiché : "Jane Street"
    source: Source
    token: str                 # jeton du board : slug Greenhouse, tenant Workday…
    extra: Mapping[str, str]   # paramètres propres à la source (site Workday, etc.)
    sector: str                # "hedge_fund" | "prop_trading" | "bank" | "asset_manager" | "vendor" | "crypto"
    hq_country: str            # ISO-3166 alpha-2
    priority: int              # 1 = sondé à chaque cycle, 3 = hebdomadaire
    enabled: bool
```

### 2.2 Collecte

```python
class RawPosting(BaseModel, frozen=True):
    source: Source
    company_slug: str
    source_job_id: str         # identifiant chez la source ; unique avec (source, company_slug)
    url: str                   # URL de candidature, canonique côté source
    title_raw: str
    description_raw: str       # texte ou HTML, tel que servi
    location_raw: str | None
    department_raw: str | None
    posted_at_raw: str | None  # non parsé : les sources mentent et changent de format
    payload: bytes             # charge utile d'origine, compressée zstd — JAMAIS jetée
    fetched_at: datetime       # aware UTC
    content_hash: str          # sur (title_raw, description_raw, location_raw)
```

### 2.3 Normalisation

```python
class Location(BaseModel, frozen=True):
    city: str | None
    country: str | None        # ISO-3166 alpha-2
    region: str | None         # "emea" | "amer" | "apac"
    remote_mode: RemoteMode
    raw: str | None            # toujours conservé : le parsing sera toujours faux quelque part

class Compensation(BaseModel, frozen=True):
    amount_min: Decimal | None
    amount_max: Decimal | None
    currency: str | None       # ISO-4217 ; None si le montant est None
    period: SalaryPeriod | None
    bonus_mentioned: bool
    equity_mentioned: bool
    raw: str | None

class Posting(BaseModel, frozen=True):
    # identité
    posting_id: str            # ULID, attribué à la première insertion
    fingerprint: str           # clé de dédoublonnage inter-sources — voir §3.4
    source: Source
    company_slug: str
    source_job_id: str
    url: str
    # contenu normalisé
    title: str                 # nettoyé : codes de req et suffixes marketing retirés
    role_family: RoleFamily
    seniority: Seniority
    min_years: int | None      # années d'expérience exigées, None si non dit
    phd_required: bool
    locations: tuple[Location, ...]   # une offre peut être multi-sites
    compensation: Compensation
    visa_sponsorship: VisaStatus
    tech: frozenset[str]       # identifiants normalisés : "cpp", "python", "kdb", "rust"
    languages_required: frozenset[str]  # ISO-639-1, vide si non exigé
    # dates — voir 09-CONVENTIONS.md §3
    posted_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    closes_at: datetime | None # date de clôture quand la source l'annonce
    # traçabilité
    resolver_stage: str        # quel étage a tranché : "rules" | "llm" | "fallback"
    normalize_version: int     # incrémenté à chaque changement de cascade — permet le rejeu ciblé
```

### 2.4 Qualification

```python
class Reason(BaseModel, frozen=True):
    code: str                  # identifiant stable : "title_match", "senior_only", "no_sponsorship"
    delta: int                 # points gagnés (>0) ou perdus (<0)
    evidence: str | None       # l'extrait de texte qui justifie — affiché dans l'UI

class MatchVerdict(BaseModel, frozen=True):
    posting_id: str
    score: int                 # 0 → 100
    tier: Tier
    reasons: tuple[Reason, ...]
    rejection_reason: str | None  # renseigné si et seulement si tier == REJECTED
    profile_version: int       # version de configs/profile.yaml appliquée
    scored_at: datetime
```

**Invariant I5** : `tier == REJECTED` ⟺ `rejection_reason is not None`.

---

## 3. Contrats par package

### 3.1 `collect`

```python
class CollectResult(BaseModel, frozen=True):
    board: Board
    postings: tuple[RawPosting, ...]
    requests_made: int
    duration_ms: int
    truncated: bool            # True si le budget de requêtes a coupé la pagination

class Collector(Protocol):
    source: Source
    def fetch(self, board: Board, session: HttpSession) -> CollectResult: ...
```

Quatre lignes, et c'est tout ce qu'un collecteur doit implémenter. Il **ne**
persiste pas, **ne** normalise pas, **ne** décide pas de la cadence.

```python
# collect/http.py — la politique, unique et partagée
class HttpSession(Protocol):
    def get_json(self, url: str, *, params: Mapping[str, str] | None = None) -> Any: ...
    def get_text(self, url: str, *, params: Mapping[str, str] | None = None) -> str: ...
    def post_json(self, url: str, *, json: Mapping[str, Any]) -> Any: ...   # Workday
```

`HttpSession` porte la cadence, la gigue, le repli exponentiel, le budget de
requêtes et les en-têtes. **Un collecteur qui construit son propre client HTTP
est un bug**, et `import-linter` D8 ne le verra pas — c'est à la revue de le
voir.

### 3.2 `normalize`

```python
def normalize(raw: RawPosting, *, taxonomy: Taxonomy, geo: GeoIndex) -> Posting: ...

# étages, tous purs, tous testables isolément
def parse_location(text: str | None, *, geo: GeoIndex) -> tuple[Location, ...]: ...
def parse_seniority(title: str, description: str) -> tuple[Seniority, int | None]: ...
def parse_compensation(description: str, *, country: str | None) -> Compensation: ...
def parse_visa(description: str) -> tuple[VisaStatus, str | None]: ...  # (statut, extrait justificatif)
def parse_tech(description: str, *, taxonomy: Taxonomy) -> frozenset[str]: ...
def classify_role(title: str, description: str, *, taxonomy: Taxonomy) -> RoleFamily: ...
def fingerprint(company_slug: str, title: str, country: str | None, posted_at: datetime | None) -> str: ...
```

**Aucune de ces fonctions n'ouvre de socket, de fichier ou de base.** `Taxonomy`
et `GeoIndex` sont des structures chargées en amont par `runtime` et passées en
argument — c'est ce qui les rend triviales à substituer en test.

### 3.3 `match`

```python
def evaluate(posting: Posting, *, profile: Profile) -> MatchVerdict: ...
def hard_reject(posting: Posting, *, profile: Profile) -> str | None: ...  # motif, ou None

# WP12 — préfiltre et LLM
def is_ambiguous(
    posting: Posting, verdict: MatchVerdict, *, profile: Profile, description: str
) -> bool: ...
def classify_llm(
    posting: Posting, *, description: str, timeout_s: int, base_url: str, model: str,
    client: httpx.Client | None = None,  # couture de test uniquement
) -> LlmVerdict | None: ...  # None = indisponible
def apply_llm_verdict(posting: Posting, llm_verdict: LlmVerdict) -> Posting: ...  # pur
def resolve_residual(
    posting: Posting, verdict: MatchVerdict, *, profile: Profile, settings: Settings,
    description: str, client: httpx.Client | None = None,
) -> MatchVerdict: ...  # préfiltre → appel → seuil de confiance → recalcul par evaluate()
```

`description` est un paramètre à part parce que `Posting` ne porte pas le texte
de l'annonce (il vit dans `posting_search_text`, relu par
`store.search.get_description`). `resolve_residual` n'est pas encore branché
dans `runtime.pipeline.ingest` : ce câblage est hors du périmètre de WP12
(`dependencies.md` : `runtime/pipeline.py` y est en lecture seule).

`classify_llm` retourne `None` quand le serveur est occupé ou indisponible :
**ce n'est pas une erreur**, c'est un tour sauté. L'offre repart en file
différée. Voir [wp/WP12-match-llm.md](wp/WP12-match-llm.md) §4.

### 3.4 Dédoublonnage — le contrat qui évite un flux illisible

```python
def fingerprint(company_slug, title, country, posted_at) -> str
```

L'empreinte est calculée sur :

| Composant | Transformation |
|---|---|
| société | `company_slug` du registre, ou slug dérivé du nom pour un agrégateur |
| titre | minuscules, ponctuation retirée, codes de req retirés, mots vides de recrutement retirés (`f/h`, `m/f/d`, `2026 start`) |
| pays | code ISO-3166 alpha-2, ou `"??"` si inconnu |
| date | **compartiment de 14 jours** sur `posted_at` si présent, sinon ignoré |

**Résolution des collisions**, dans cet ordre strict :

1. Si une offre existe déjà avec la même empreinte et une **source ATS**, la
   nouvelle offre devient un **alias** — ligne dans `posting_aliases`, aucune
   nouvelle offre.
2. Si l'offre existante vient d'un **agrégateur** et la nouvelle d'un **ATS**,
   l'ATS **prend la place canonique** : l'offre existante devient l'alias, ses
   favoris et son historique suivent.
3. Deux ATS différents avec la même empreinte : la plus ancienne reste
   canonique, un avertissement est journalisé (cas réel : une société qui migre
   d'ATS).

Le compartiment de date à 14 jours est délibérément large : un agrégateur
republie souvent avec sa propre date d'indexation, décalée de plusieurs jours de
la publication réelle. Trop serré, on duplique ; trop large, on fusionne deux
campagnes successives — 14 jours est le compromis, et il est **configurable**
dans `configs/sources.yaml`.

### 3.5 `store`

```python
class PostingFilter(BaseModel, frozen=True):
    """Le contrat de filtrage, partagé entre l'API et le store. Un seul endroit."""
    countries: frozenset[str] = frozenset()
    cities: frozenset[str] = frozenset()
    companies: frozenset[str] = frozenset()
    sectors: frozenset[str] = frozenset()
    sources: frozenset[Source] = frozenset()
    role_families: frozenset[RoleFamily] = frozenset()
    seniorities: frozenset[Seniority] = frozenset()
    remote_modes: frozenset[RemoteMode] = frozenset()
    tech_all: frozenset[str] = frozenset()    # ET logique
    tech_any: frozenset[str] = frozenset()    # OU logique
    visa: frozenset[VisaStatus] = frozenset() # défaut côté API : {sponsors, unknown}
    min_score: int = 0
    tiers: frozenset[Tier] = frozenset()
    posted_within_days: int | None = None
    query: str | None = None                  # plein texte FTS5
    favorites_only: bool = False
    include_hidden: bool = False

class SortKey(StrEnum):
    SCORE = "score"; POSTED = "posted"; SEEN = "seen"; COMPANY = "company"; CLOSES = "closes"

class Page(BaseModel, frozen=True):
    items: tuple[PostingRow, ...]
    next_cursor: str | None    # keyset opaque, jamais un OFFSET

def list_postings(conn, flt: PostingFilter, sort: SortKey, cursor: str | None, limit: int) -> Page: ...
def facet_counts(conn, flt: PostingFilter) -> FacetCounts: ...
def upsert_posting(conn, posting: Posting, verdict: MatchVerdict) -> str: ...
def record_alias(conn, canonical_id: str, alias: RawPosting) -> None: ...
def mark_favorite(conn, posting_id: str, value: bool) -> None: ...
```

**`PostingFilter` est partagé entre l'API et le store, volontairement.** C'est
la seule façon d'éviter la dérive classique où un filtre existe dans l'URL, mais
pas dans le SQL, et ne filtre rien sans que personne ne s'en aperçoive.

**Contrat de facettes** : `facet_counts` renvoie les comptes **sous le filtre
courant, sauf sur la dimension comptée**. Sélectionner `country=GB` ne doit pas
faire tomber à zéro toutes les autres lignes du filtre pays — sinon on ne peut
plus changer d'avis sans tout réinitialiser. C'est l'invariant **I6**.

### 3.6 `api` — surface publique

| Route | Paramètres | Réponse |
|---|---|---|
| `GET /postings` | tous les champs de `PostingFilter` en query, `sort`, `cursor`, `limit` (≤100) | `Page[PostingOut]` |
| `GET /postings/{id}` | — | `PostingDetailOut` (description complète, raisons du score, alias) |
| `POST /postings/{id}/favorite` | `{value: bool}` | `204` |
| `POST /postings/{id}/hide` | `{value: bool}` | `204` |
| `GET /facets` | mêmes filtres que `/postings` | `FacetCounts` |
| `GET /companies` | `sector`, `country` | `list[CompanyOut]` avec santé et compte d'offres |
| `GET /health` | — | état par source, fraîcheur du flux, version du schéma |

`limit` est plafonné à 100 côté serveur. Les tableaux de query params suivent la
forme répétée (`?countries=GB&countries=US`), pas la forme CSV : c'est ce que
FastAPI génère nativement et ce que le générateur de types TypeScript comprend.

---

## 4. Ce qui n'est PAS dans ce fichier

Les signatures internes à un package. Un lot est libre de son découpage interne
tant qu'il respecte les contrats ci-dessus. Si un lot a besoin d'exposer une
fonction supplémentaire à un autre package, **elle vient ici d'abord**, dans un
commit qui ne fait que ça.
