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

### 2.2 Unification avec WP18 (étape 3)

Le statut posé sur une offre du feed **devient** une candidature liée (`source = feed`) ; la
colonne `user_flags.application_status` est migrée puis lue depuis `applications`. Une seule
vérité : la pastille du feed et l'onglet Applications ne peuvent pas diverger.

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
rendu par le Chromium déjà présent dans l'image (`page.pdf()`), rangé en `offer.pdf` dans le
dossier de la candidature — l'offre reste lisible le jour où elle disparaît du site. Le même PDF
est téléchargeable depuis le panneau de détail.

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

## 6. Front — onglet Applications (étape 5)

Table dense (société, intitulé, lieu, candidature, réponse, délai, statut), filtres statut /
année / pays, panneau de détail avec captures, CV envoyé et historique ; statistiques : taux de
réponse, délai médian, taux d'entretien par type de poste et par variante de CV.

## 7. Étapes

| # | Livrable |
|---|---|
| 1 | Migration `0011`, `store.applications`, `career.sheet` + `career.dossier` + `career.reconcile`, CLI `import-applications` |
| 2 | PDF de l'offre à la candidature (§4) |
| 3 | Unification avec WP18 (statut du feed = candidature liée) |
| 4 | `cv context`, `cv build`, `apply`, skill `tailor-cv` |
| 5 | API `/applications` + onglet Applications |
