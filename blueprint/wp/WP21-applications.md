# WP21 — Le dossier de candidature : historique, pièces, CV ciblé

> **Contexte** : le mainteneur a postulé ~250 fois depuis mai 2024, hors JobTracker pour
> l'essentiel. La trace en est éclatée en deux endroits : une Google Sheet (pays, société, date de
> candidature, date de refus, motif — l'intitulé n'apparaît qu'à partir de 2026) et un dossier
> `Société/Intitulé/` avec les captures de l'offre et le CV envoyé (PDF, parfois `.tex`). WP18 ne
> sait suivre que des offres **collectées**, sans date de candidature ni pièce jointe. Ce lot fait
> de la **candidature** un objet à part entière, y verse l'historique, et outille la rédaction
> d'un CV ciblé par offre — rédigé dans Claude Code, compilé et archivé par JobTracker.

**Dépend de** : WP02 (stockage), WP07 (API), WP18 (statut sur l'offre).

---

## 1. Données personnelles : rien dans le dépôt

Le dépôt est **public**. CV, téléphone, captures, historique : tout vit sous `data/career/`
(`data/` est ignoré par git), jamais ailleurs.

```
data/career/
  master/cv.tex            CV maître : le point de départ de chaque CV ciblé
  master/facts.md          tout ce qui est vrai et chiffré, plus long qu'un CV (la réserve du LLM)
  applications/<dossier>/  une candidature : captures (historique) ou offer.pdf, cv.tex, cv.pdf
  inbox/                   l'archive d'origine, telle quelle (jamais modifiée)
```

`<dossier>` = `<société>/<intitulé>` repris de l'archive d'origine pour l'historique, puis
`<aaaa-mm-jj>-<société>-<intitulé>` (slugs) pour les nouvelles.

## 2. Le modèle : `applications`

Migration `0011`. Une ligne = **un envoi de candidature** à un poste.

| Colonne | |
|---|---|
| `application_id` | hachage stable de (société normalisée, intitulé, date, rang du doublon) : un réimport ne duplique rien ; une ligne d'import que l'historique ne produit plus est purgée, sauf si elle porte une note |
| `company` / `title` / `location` | tels qu'écrits par l'utilisateur ; `title` NULL si inconnu (Sheet 2024-2025 sans dossier) |
| `applied_on` / `closed_on` | dates ISO ; NULL si `?` dans la Sheet. `applied_on_estimated` = 1 quand la date vient de l'horodatage des captures |
| `status` | `ApplicationStatus` (même `CHECK` que WP18) |
| `reason` | le motif d'origine (« Failed 2nd interview », « Job filled »…), jamais perdu |
| `posting_id` | l'offre collectée correspondante, si le rapprochement est sûr (`ON DELETE SET NULL`) |
| `dossier` | chemin relatif sous `data/career/applications/` |
| `origin` | `import` (l'historique) · `feed` (statut posé sur une offre) · `cli` (`jobtracker apply`) |

`application_events` garde l'**historique des statuts** (date, statut, motif) — la limite n°1
de WP18 (§5).

### 2.1 Statut depuis la Sheet

| Motif / dates | Statut |
|---|---|
| « Waiting for answer », ou pas de date de refus ni de motif | `applied` |
| « Not interested », « Job filled », « Too many CVs », date de refus seule | `rejected` |
| « Failed N(th) interview » | `rejected`, et un évènement `interview` antérieur |

### 2.2 Unification avec WP18 — une seule vérité

- `applications` est la source. `user_flags.application_status` reste, comme **miroir** : toutes
  les requêtes du feed (filtres, export, rétention) filtrent dessus sans changer. Seul
  `store.applications` l'écrit (`_mirror`), après chaque changement d'une candidature liée.
- Le select de statut du panneau (`POST /postings/{id}/status`) passe par `api.tracking.track_posting`,
  **le même code** que `jobtracker app add --posting` :
  1. l'offre a déjà une candidature → un pas d'historique (`record_status`) ;
  2. sinon, une candidature **saisie à la main ou importée** chez le même employeur, à ±4 jours,
     même intitulé/lieu, est rattachée (`career.feedlink`) — postuler hors pipeline puis voir
     l'offre collectée ne fait pas de doublon ;
  3. sinon, elle est créée (`origin = feed`) avec son dossier, et `offer.pdf` est rendu **après**
     la réponse (tâche de fond) : un échec de rendu est journalisé, jamais bloquant.
- `null` (« Not tracking ») : une candidature créée par le feed est supprimée (ses fichiers
  restent sur le disque) ; une autre est seulement détachée de l'offre.
- Reprise des statuts d'avant (`jobtracker app adopt-feed`) : un statut qui correspond à une
  candidature de l'historique y est rattaché (l'historique en sait plus : le refus apparaît dans
  le feed) ; les `applied` restants deviennent des candidatures ; les `withdrawn` sans candidature
  étaient le « pas pour moi » d'avant le triage → `triage = no`. Les `applied` réclament leur
  candidature avant les `withdrawn` (deux offres jumelles, l'une postulée, l'autre écartée).

### 2.3 Abandon : cinq mois sans nouvelles

Une candidature `applied` ou `interview` sans aucun pas daté depuis **5 mois** compte comme
abandonnée (`career.lifecycle`) : elle sort de `app list --open`. **Rien n'est stocké** — ni
statut, ni drapeau : le jour où une nouvelle arrive, le statut enregistré suffit.

### 2.4 Retouches à la main et ré-import

Une ligne importée que personne n'a touchée a `updated_at = created_at`. Un ré-import ne
rafraîchit — et ne purge — que celles-là : un statut, une note, un lien posés à la main survivent.
L'identifiant d'une ligne importée dérive du nom **tel qu'écrit** (pas de la clé de
rapprochement) : ajouter un alias ne change l'identité de personne.

## 2bis. Le ad hoc d'abord — `jobtracker app` (`just app …`)

Rien n'exige le collecteur. Une offre vue sur LinkedIn, un mail de recruteur, une cooptation :

| | |
|---|---|
| `app add --company C --title T [--location L] [--url U] [--text F\|-] [--attach cv.pdf …] [--date D] [--note N]` | `--text` : le texte collé, mis en page en PDF ; `--url` seul : la page imprimée en PDF par Chromium ; une URL déjà collectée bascule sur l'offre |
| `app add --posting <id>` | depuis une offre collectée : même chemin que le feed |
| `app status <id> interview\|offer\|rejected\|withdrawn [--date] [--reason]` | un pas d'historique |
| `app list [--open] [--status S] [--company X]` · `app show <id>` | `--open` applique la règle des 5 mois |
| `app edit` · `app link <id> <posting\|none>` · `app attach <id> fichiers…` · `app pdf <id> [--url\|--text]` · `app rm <id> --yes` | |
| `app adopt-feed [--apply] [--no-pdf]` | reprise des statuts posés dans le feed avant WP21 |

Les identifiants se donnent par préfixe unique, comme un sha git.

## 3. Import de l'historique — `jobtracker import-applications`

Package **`jobtracker.career`** : n'importe que `core` (contrat D11). Lecture de fichiers locaux
seulement, aucun réseau.

1. **Sheet** (`career.sheet`) : la Sheet est une grille calendrier — des blocs de colonnes côte
   à côte (5 colonnes, puis 6 avec `Job` à partir de 2026), des lignes de mois, des lignes de
   totaux. Le parseur repère chaque ligne d'en-tête, découpe les blocs, ignore mois et totaux,
   lit les dates `jj/mm/aaaa`, et **signale** toute cellule qu'il ne comprend pas.
2. **Dossier** (`career.dossier`) : `Société/[Intitulé/...]` → une candidature par dossier
   feuille contenant des captures ou un CV. `Old/`, `New folder/`, le hub `CV/` et les venv sont
   écartés, avec motif.
3. **Rapprochement** (`career.reconcile`) Sheet ↔ dossier : société par nom normalisé + alias
   (`configs/company_aliases.yaml` : QRT = QubeRT = Qube Research & Technologies, JPMC = JP
   Morgan…), puis intitulé et lieu (NY, SG, UK, HK…). Un dossier ambigu entre plusieurs lignes
   n'est **pas** deviné : il est rapporté.
4. **Lien vers le feed** : société du registre + intitulé proche + pays → `posting_id`.
5. Dry-run par défaut ; le rapport (appariés, orphelins des deux côtés, ambigus, cellules
   illisibles) s'écrit en JSONL. `--apply` copie les pièces sous `data/career/applications/` et
   écrit la base. Idempotent.

## 4. Le PDF de l'offre, au moment de postuler

L'historique garde ses captures telles quelles : **pas d'OCR**. Pour une offre collectée, la
capture d'écran est remplacée par un **PDF propre** produit par JobTracker au moment où l'on
passe l'offre en `applied` : intitulé, société, lieu(x), rémunération, visa, lien d'origine, date
de collecte et date de candidature en tête, puis la description complète. Gabarit HTML maison,
rendu par le Chromium déjà présent dans l'image (`page.pdf()`), hors ligne (toute requête de la
page est coupée), rangé en `offer.pdf` dans le dossier de la candidature — l'offre reste lisible
le jour où elle disparaît du site. Bouton **Offer PDF** du panneau de détail :
`GET /postings/{id}/offer.pdf` sert la copie archivée, sinon la rend à la volée (503 sans
navigateur). Hors pipeline : `app add --text` (mise en page du texte collé) ou `--url` (la page
elle-même imprimée, `collect.browser.BrowserClient.print_pdf`).

## 5. CV ciblé — rédigé dans Claude Code

Le LLM du CV, c'est la session Claude Code ; JobTracker fournit le contexte et la chaîne.

- `jobtracker cv context <posting_id|application_id>` imprime : le texte de l'offre, le CV
  maître, `facts.md`, et les 3 CV passés les plus proches (par intitulé) **avec leur issue**
  (refus en 2 jours vs entretien).
- Le skill projet `tailor-cv` (`.claude/skills/`) déroule : contexte → rédaction libre de
  `cv.tex` → compilation → contrôle **une page** → diff contre le maître → relecture par
  l'utilisateur → `jobtracker apply` enregistre la candidature (date du jour, CV archivé).
- **Rédaction libre, faits verrouillés** : la formulation, l'ordre, l'accroche et la sélection
  sont libres ; un chiffre, un outil, un employeur ou un diplôme absent de `cv.tex` maître et de
  `facts.md` ne l'est pas. Le skill liste chaque affirmation nouvelle pour la relecture.
- Compilation : `tectonic` (binaire unique, paquets à la demande), lancé dans un conteneur.

## 6. Front — onglet Applications (`/applications`)

- **API** (`api/routes/applications.py`) : `GET /applications` (toutes, quelques centaines :
  l'onglet filtre lui-même), `GET /applications/{id}` (historique, pièces, offre liée),
  `POST /applications` (saisie à la main ; une URL collectée lie l'offre ; le texte collé devient
  `offer.pdf`), `POST …/status`, `…/edit`, `…/delete`, `…/offer`, `…/files?name=` (le fichier en
  corps brut — pas de dépendance multipart), `GET …/files/{chemin}` (seulement un fichier
  *listé* du dossier : aucune sortie possible). Tout passe par `api.tracking`, comme la CLI.
- `open`, `abandoned`, `last_news_on`, `reached_interview` sont **calculés à chaque lecture**
  (`career.lifecycle`, §2.3) — jamais stockés, jamais recalculés par le front.
- **Écran** : bandeau de chiffres (total, ouvertes, entretiens, offres, refus, sans nouvelles
  depuis 5 mois, taux de réponse, délai médian d'un refus) ; vues *Open* (défaut) / *All* /
  *Interviews* / *Offers* / *Rejected* / *No news 5+ months*, recherche sans accents, année,
  tri par colonne — l'état vit dans l'URL ; table dense, ligne grisée si abandonnée.
- **Panneau** `/applications/p/{id}` : statut + historique daté, nouvelle étape (statut choisi
  explicitement, date, motif), note (sauvée en quittant le champ), pièces (captures en vignettes,
  PDF/CV en liens, envoi d'un fichier), PDF de l'offre (depuis l'offre liée ou un texte collé),
  correction des champs, suppression confirmée (les fichiers restent sur le disque).
- **New application** : formulaire de saisie à la main, texte de l'offre collé → `offer.pdf`.

## 7. Étapes

| # | Livrable |
|---|---|
| 1 | *(fait)* Migration `0011`, `store.applications`, `career.sheet` + `career.dossier` + `career.reconcile`, CLI `import-applications` |
| 2 | PDF de l'offre à la candidature (§4) — fait |
| 3 | Unification avec WP18 (§2.2), ad hoc `jobtracker app` (§2bis) — fait |
| 4 | *(mis de côté, #6)* `cv context`, `cv build`, `apply`, skill `tailor-cv` |
| 5 | API `/applications` + onglet Applications (§6) — fait |
