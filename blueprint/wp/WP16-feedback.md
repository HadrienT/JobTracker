# WP16 — Boucle d'amélioration : rejeu, rapport, rétention

> **Contexte** : le lot qui rend le projet **améliorable au lieu de simplement
> fonctionnel**. Sans lui, « j'ai amélioré le parseur de séniorité » est une
> affirmation invérifiable.
>
> Tout repose sur une décision prise très tôt : l'archive brute compressée de
> chaque offre (interdit n°10). Elle permet de rejouer le normaliseur sur des
> mois de données réelles et de **mesurer** le delta, au lieu de constater que
> « ça a l'air mieux ».

**Fichiers à lire** : ce fichier · [04-DATA-MODEL.md](../04-DATA-MODEL.md) §6 ·
[08-TESTING.md](../08-TESTING.md) §2 · [07-ERRORS-AND-LOGGING.md](../07-ERRORS-AND-LOGGING.md) §4

**Dépend de** : WP02 · WP08. **Parallélisable avec** : WP15.

---

## 1. Objectif

`replay.py`, `report.py`, `retention.py`, et la boucle qui relie les favoris au
réglage du profil.

---

## 2. Rejeu — `jobtracker replay`

```sh
jobtracker replay --since 2026-01-01 --dry-run          # diff sans écrire
jobtracker replay --stage seniority --dry-run           # un seul étage
jobtracker replay --normalize-version-below 7           # ciblé par version
jobtracker replay --apply
```

Ce que le rejeu produit, en `--dry-run` :

```text
rejeu sur 12 480 offres archivées, normalize_version 6 → 7

étage         avant    après    delta
seniority     71.2%    84.6%    +13.4 pts
visa          58.9%    59.1%    +0.2 pts
location      92.1%    91.4%    -0.7 pts   ⚠ RÉGRESSION

changements de palier :  +142 possible,  -31 rejected,  -8 strong  ⚠
```

**La ligne de régression est la raison d'être de l'outil.** Une amélioration du
parseur de séniorité qui casse 0,7 point de résolution de lieu est un arbitrage
qu'on doit voir avant de le committer, pas découvrir trois semaines plus tard.

Les changements de palier `-8 strong` méritent une inspection systématique : huit
offres sont sorties du flux principal. C'est peut-être une correction, c'est
peut-être un bug.

Règles :

| Règle | Raison |
|---|---|
| `--dry-run` par défaut | Un rejeu qui écrit par accident est irréversible |
| Les `user_flags` sont **intouchables** | Un favori survit à tout rejeu |
| Le rejeu **ne recollecte jamais** | Il lit `raw_payloads`, uniquement |
| `posting_id` et `first_seen_at` sont conservés | Sinon on perd l'historique de détection |

---

## 3. Rapport hebdomadaire — `jobtracker report --weekly`

| Section | Contenu | À quoi ça sert |
|---|---|---|
| Couverture | Sociétés actives, offres par secteur et par pays | Voir ce que le registre manque |
| Santé des sources | Sources muettes, en chute de volume, en erreur | P3, sous une forme lisible |
| **Sociétés à zéro offre depuis 30 jours** | Liste nominative | Le signal le plus fiable d'un jeton cassé |
| Résolution du normaliseur | Taux par étage, évolution sur 4 semaines | La mesure de progrès |
| Distribution des paliers | Combien de `strong` par semaine | Si ça tombe à zéro, le profil est trop strict |
| Motifs de rejet | Les 10 plus fréquents | Un `not_quant` à 80 % sur une source dit qu'elle est mal ciblée |
| Charge LLM | Appels, secondes de GPU, tours sautés | Vérifie le modèle d'entonnoir de WP12 |
| **Employeurs inconnus** | Vus chez les agrégateurs, absents du registre | Alimente WP00 en continu |

Le rapport sort en markdown dans `docs/reports/`, daté. C'est un artefact qu'on
relit trois mois plus tard pour comprendre une dérive.

---

## 4. Boucle favoris → profil

Le seul signal d'apprentissage disponible : ce que l'utilisateur met en favori.

| Analyse | Ce qu'elle révèle |
|---|---|
| Distribution du score des favoris | Si les favoris sont majoritairement en `possible`, les poids sont mal réglés |
| Favoris sur des offres `stretch` ou `rejected` | **Le signal le plus précieux** : le filtre écarte des offres désirables |
| Motifs de rejet des offres mises en favori | Nomme précisément la règle trop stricte |
| Sociétés et stacks sur-représentées dans les favoris | Suggestion de réglage des poids |

**Le rapport propose, il ne modifie rien.** `configs/profile.yaml` reste écrit à
la main, relu en diff, versionné. Une boucle qui s'auto-ajuste dériverait sans
qu'on puisse dire quand ni pourquoi — et rendrait le scoring non reproductible,
ce que l'ADR-006 interdit.

---

## 5. Rétention — `retention.py`

Applique le tableau de [04-DATA-MODEL.md](../04-DATA-MODEL.md) §6. Tourne une
fois par jour depuis l'ordonnanceur.

| Piège | Parade |
|---|---|
| Purger `raw_payloads` casse le rejeu | Rétention à **365 jours**, délibérément longue |
| `ON DELETE CASCADE` mal placé efface des favoris | `user_flags` n'est **jamais** purgée |
| Purger pendant une collecte verrouille la base | Par lots, hors fenêtre de collecte |

---

## 6. Tests attendus

| Test | Attendu |
|---|---|
| Rejeu `--dry-run` | **aucune écriture**, diff produit |
| Rejeu `--apply` sur 1 000 offres | `posting_id`, `first_seen_at` et `user_flags` conservés |
| Rejeu avec un normaliseur dégradé | régression **détectée et signalée** |
| Rejeu ciblé par étage | seuls les champs de l'étage changent |
| Rapport sur une base de démonstration | toutes les sections renseignées |
| Société à zéro offre depuis 30 j | apparaît nominativement |
| Favoris sur des offres `rejected` | signalés avec leur motif de rejet |
| Rétention | `raw_payloads` purgés, `postings` conservées, `user_flags` **intactes** |
| Rétention pendant une collecte simulée | aucun verrou long |

---

## 7. Critères d'acceptation

- [ ] `jobtracker replay --dry-run` produit le tableau de delta par étage.
- [ ] Une régression de résolution est **détectée et signalée** explicitement.
- [ ] Le rejeu ne recollecte jamais et n'écrit jamais sans `--apply`.
- [ ] `user_flags` survit à un rejeu complet, vérifié par un test.
- [ ] Le rapport hebdomadaire couvre les huit sections du §3.
- [ ] Le rapport **propose** des ajustements de profil sans jamais les appliquer.
- [ ] La rétention respecte [04-DATA-MODEL.md](../04-DATA-MODEL.md) §6 et ne
      purge jamais `user_flags`.
- [ ] `mypy --strict` passe.

---

## 8. Écarts et décisions à l'implémentation

| Sujet | Décision | Pourquoi |
|---|---|---|
| **Source du rejeu** | Les entrées archivées que `normalize()` consomme (titre, description, lieu, date), pas les `raw_payloads` | Une charge utile est le JSON propre à chaque ATS ; la remettre en `RawPosting` exigerait de rejouer les neuf mappeurs de collecteurs (dont certains dépendent du `Board`). La description brute était déjà conservée intégralement ; la migration **0005** ajoute `location_raw` et `posted_at_raw` exacts. Avant 0005, repli sur les lieux déjà parsés. Le rejeu ne recollecte jamais et n'importe ni `httpx` ni `collect` (test) |
| **Deltas de palier** | `evaluate(avant)` et `evaluate(après)` au **même instant** | Sinon une offre qui vieillit entre deux exécutions passerait pour un effet du parseur |
| **Offres tranchées par le LLM** | Les champs du LLM ne sont jamais écrasés par les règles | Le rejeu ne ferait que défaire ce que le LLM a réglé |
| **`--apply` sur une régression** | Refusé sans `--allow-regression` ; code retour 1 | Une régression ne doit jamais passer en silence dans un script |
| **Rétention** | Par lots bornés (500) avec `COMMIT` entre chaque, quotidienne depuis `jobtracker loop` | Un seul `DELETE` géant garde le verrou d'écriture WAL et fait attendre les favoris de l'API |

**Un défaut corrigé au passage** : `purge_inactive_postings` supprimait les offres
inactives depuis plus de 180 jours, et `user_flags.posting_id` étant en
`ON DELETE CASCADE`, un favori disparaissait avec son offre — l'inverse de la
règle « un favori survit à la disparition de l'offre ». Une offre portant un
`user_flags` est désormais exemptée de la purge. De même, `update_resolution`
ne réactive plus une offre inactive.

**Non mesuré** : la charge LLM du rapport est une estimation (les appels mis en
quarantaine ne sont pas persistés) — le rapport le dit.
