# WP22 — Le registre des CV : quel CV est parti avec quelle candidature

> **Prérequis** : WP21 (table `applications`, dossiers). **Débloque** : WP21 §5 (#6) — `jobtracker
> apply` enregistrera ses CV ciblés ici.

## 1. Le problème

Le CV envoyé n'était qu'un fichier parmi d'autres dans le dossier de la candidature : la base
ignorait quelle version était partie, et le nom ne dit rien (71 fichiers `CV_<Nom>.pdf`, une
quinzaine de contenus). Le gain n'est pas la place disque (10 Mo → 6 Mo) : c'est de pouvoir
répondre à « quel CV ? » et d'en mesurer l'effet.

## 2. Le modèle

- `cvs` : un CV = un contenu. `cv_id` est le SHA-256 du fichier, rangé une seule fois sous
  `data/career/cvs/<cv_id>.pdf` — données personnelles, jamais dans le dépôt.
- `pinned` : une **version**, proposée dans les menus. Un CV écrit pour une offre n'y figure pas.
- `applications.cv_id` : un seul CV par candidature. L'offre le retrouve par `posting_id`.
- `applications.cv_source` : `confirmed` (choisi par l'utilisateur, ou conservé dans le dossier au
  moment de l'envoi) ou `inferred` (supposé). Le taux de réponse par version vaut ce que vaut cette
  colonne : ne jamais présenter un lien déduit comme un fait.

## 3. La reprise de l'existant

`just app cv backfill` : dry-run par défaut, `--apply`, `--report f.jsonl`, relançable après un
import. Règles :

| Cas | Traitement |
|---|---|
| un seul CV PDF dans le dossier | lié, `confirmed` |
| fichier nommé par `--inferred-name` | lié, `inferred` (mis là après coup) |
| CV du dossier **et** du dossier parent | celui du dossier : le parent servait aux candidatures plus anciennes |
| aucun CV dans le dossier, un dans le parent | celui du parent |
| plusieurs contenus dans le dossier | **ambigu** : rapporté, pas lié |
| un `CV*.pdf` qui n'est pas un PDF | rapporté, pas lié |
| PDF sans « cv » dans son nom | ignoré : c'est souvent une offre mise en page en LaTeX, `.tex` compris |

Une candidature qui a déjà un CV n'est jamais touchée. Un CV envoyé plusieurs fois devient une
version (nommée d'après son fichier, à renommer) ; envoyé une fois, il prend le nom de l'offre.
`created_at` = sa première date d'envoi, pas celle de la reprise. La reprise ne bouge pas
`updated_at` : ce n'est pas une édition à la main, la ligne reste rafraîchissable par l'import, et
le rafraîchissement conserve le lien.

Les copies restent dans les dossiers : ce sont les archives d'origine, et les supprimer ne libère
que 4 Mo. Si on le fait un jour, c'est un lot à part, une fois les liens vérifiés.

## 4. L'API

`GET /cvs`, `POST /cvs?name=` (corps brut, PDF seulement, mêmes octets = même CV),
`POST /cvs/{id}/edit`, `GET /cvs/{id}/file`, `POST /applications/{id}/cv`.
`ApplicationOut` porte `cv_id` et `cv_source`.

## 5. Ne plus oublier

- **Version en cours** (`store.cvs.current_cv_id`) : la version épinglée envoyée — ou ajoutée — le
  plus récemment. Jamais un CV ciblé : celui de l'offre d'hier n'est pas celui de l'offre de demain.
- Marquer une offre `applied` dans le feed, ou créer une candidature sans préciser de CV, suppose
  cette version, en `inferred`. Dans le formulaire « New application », le menu la présélectionne ;
  soumettre, c'est répondre : `confirmed`. `cv_id: null` explicite veut dire « aucun ».
- Attacher un CV en pièce jointe (`Files`, `app attach`) l'enregistre et le lie, sauf si
  l'utilisateur avait déjà choisi.
- Le filtre **No CV** de l'onglet Applications liste ce qui reste à remplir ; le `?` de la colonne CV
  signale un lien supposé, confirmé d'un clic dans la fiche.

## 6. Sauvegarde

La base pointe vers des fichiers qu'elle ne contient pas : `jobtracker backup` archive aussi
`data/career/` (`career-*.tar.gz`, relue avant d'être gardée, 7 jours). Sans cette archive, restaurer
la base seule laisserait des `cv_id` sans fichier.

## 7. Hors périmètre

CV ciblé généré (WP21 §5, #6), plusieurs CV par candidature, suppression d'un CV, purge des copies.
