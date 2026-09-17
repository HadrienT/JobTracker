# 05 — Séquences bout-en-bout

> Prérequis : [01-ARCHITECTURE.md](01-ARCHITECTURE.md), [03-INTERFACES.md](03-INTERFACES.md).
> À lire quand vous câblez deux composants.

---

## 1. Un cycle de collecte sur une source

```mermaid
sequenceDiagram
    participant S as scheduler
    participant B as breaker
    participant C as collector
    participant H as HttpSession
    participant P as pipeline
    participant N as normalize
    participant M as match
    participant D as store

    S->>B: autorisé(source) ?
    alt disjoncteur ouvert
        B-->>S: non — tour sauté
        S->>D: source_runs(status="skipped")
    else
        B-->>S: oui
        loop chaque board de la source, séquentiellement, avec gigue
            S->>C: fetch(board, session)
            C->>H: get_json(...)
            H-->>C: charge utile
            C-->>S: CollectResult(postings, requests_made)
            S->>P: ingest(result)
            P->>D: archive brute (zstd) + upsert RawPosting
            P->>N: normalize(raw)
            N-->>P: Posting (+ fingerprint)
            P->>D: résolution d'empreinte
            alt empreinte connue et canonique ATS
                D-->>P: alias
                P->>D: record_alias(...)
            else
                P->>M: evaluate(posting, profile)
                M-->>P: MatchVerdict
                P->>D: upsert_posting(posting, verdict)
            end
        end
        S->>D: source_runs(fetched, new, updated, aliased, rejected, status)
        S->>B: succès/échec
    end
```

Trois points à ne pas rater :

1. **Le dédoublonnage précède le scoring.** Scorer un alias, c'est brûler du CPU
   et — si le LLM s'en mêle — du GPU, pour une ligne qui ne sera jamais affichée.
2. **L'archive brute est écrite avant la normalisation.** Si le normaliseur
   plante sur une offre exotique, la charge utile est déjà en base et le rejeu
   pourra la reprendre. L'ordre inverse perd précisément les cas intéressants.
3. **`source_runs` est écrit même quand tout va bien et surtout quand il ne
   remonte rien.** C'est la matière première du chien de garde.

---

## 2. Le résidu ambigu part au LLM (WP12)

```mermaid
sequenceDiagram
    participant P as pipeline
    participant F as prefilter
    participant Q as file différée
    participant L as match.llm
    participant S as llama-server
    participant D as store

    P->>F: is_ambiguous(posting, verdict) ?
    alt non
        F-->>P: verdict déterministe conservé
    else oui
        F->>Q: mise en file (voie différée)
    end

    Note over Q: vidée toutes les 30 min
    Q->>L: lot de N offres
    L->>S: GET /health
    alt serveur occupé ou indisponible
        S-->>L: 503
        L->>Q: remise en file, attempts += 1
    else disponible
        L->>S: POST /v1/chat/completions (json_schema contraint)
        S-->>L: verdict structuré
        L->>D: verdict mis à jour, resolver_stage="llm"
    end
```

La voie **urgente** (offre potentiellement `strong` chez une société de rang 1)
tente l'appel immédiatement au lieu de passer par la file. Elle reste rare, par
construction : voir [wp/WP12-match-llm.md](wp/WP12-match-llm.md) §3.

---

## 3. Le front charge un écran

```mermaid
sequenceDiagram
    participant U as navigateur
    participant W as web (React)
    participant A as API
    participant D as store

    U->>W: /?country=GB&country=US&tech=cpp&sort=score
    W->>W: décode l'URL en PostingFilter
    par en parallèle
        W->>A: GET /postings?...&limit=50
        A->>D: list_postings(filtre, tri, cursor=null)
        D-->>A: Page(items, next_cursor)
        A-->>W: 50 offres
    and
        W->>A: GET /facets?...
        A->>D: facet_counts(filtre)
        D-->>A: comptes par dimension
        A-->>W: facettes
    end
    W-->>U: liste virtualisée + panneau de filtres avec comptes

    U->>W: scroll en bas
    W->>A: GET /postings?...&cursor=<opaque>
    A-->>W: 50 offres suivantes
```

**L'état des filtres vit dans l'URL, pas dans un store React.** Conséquence
directe : un écran est partageable, rechargeable, et le bouton Précédent du
navigateur fonctionne. C'est aussi ce qui rend les bugs de filtre reproductibles
— on colle l'URL dans l'issue.

Les deux appels partent **en parallèle** : les facettes ne bloquent jamais
l'affichage de la liste. Une facette lente dégrade le panneau de filtres, pas le
flux.

---

## 4. Une offre disparaît d'un board

```mermaid
sequenceDiagram
    participant P as pipeline
    participant D as store

    P->>D: identifiants vus dans ce run, pour ce board
    D->>D: postings du board absents du run
    alt board a répondu avec un volume plausible
        D->>D: is_active = 0, last_seen_at inchangé
    else board a répondu ZÉRO offre
        D->>D: aucune désactivation
        D->>D: source_runs(status="empty")
    end
```

**La branche « zéro offre » est la plus importante du projet.** Un jeton devenu
invalide, un ATS qui change d'URL, un anti-bot qui sert une page vide : tous
produisent une réponse 200 avec zéro offre. Désactiver en masse sur cette base,
c'est vider le flux en silence et croire que le marché s'est arrêté.

Règle : **on ne désactive jamais sur un run à zéro**. On journalise `empty`, on
laisse les offres en place, et le chien de garde alerte si la source reste muette
plus de N cycles.

---

## 5. Un favori est posé

```mermaid
sequenceDiagram
    participant U as navigateur
    participant W as web
    participant A as API
    participant D as user_flags

    U->>W: touche « f » sur l'offre sélectionnée
    W->>W: mise à jour optimiste du cache TanStack Query
    W->>A: POST /postings/{id}/favorite {value:true}
    A->>D: UPSERT (transaction d'une instruction)
    A-->>W: 204
    alt échec
        W->>W: rollback du cache + toast
    end
```

`user_flags` est une table à part (voir [04-DATA-MODEL.md](04-DATA-MODEL.md) §2),
donc une passe de collecte concurrente qui réécrit `postings` **ne peut pas**
écraser un favori. C'est le seul point où l'API écrit, et il est conçu pour ne
jamais entrer en conflit avec l'écrivain principal.
