# Corpus doré

Une offre **réelle** par ligne dans `corpus.jsonl`, avec ses champs attendus
étiquetés à la main. C'est la vérité terrain du normaliseur (WP03) et du matcher
(WP05), et la seule mesure de progrès du projet.

Format et règles : [`blueprint/08-TESTING.md`](../../../blueprint/08-TESTING.md) §2.
Quotas de composition à atteindre : [`blueprint/wp/WP00-recon-registry.md`](../../../blueprint/wp/WP00-recon-registry.md) §4.
Schéma validé par [`tools/corpus_schema.py`](../../../tools/corpus_schema.py) et
[`tests/registry/test_corpus.py`](../../registry/test_corpus.py).

## Schéma exact d'une entrée

L'exemple de 08-TESTING.md §2 est simplifié. Le schéma réellement utilisé ici,
en attendant `core.models.Posting` (WP01) :

```json
{
  "id": "gh_optiver_4211",
  "source": "greenhouse",
  "company_slug": "optiver",
  "lang": "en",
  "title_raw": "Graduate Software Engineer (C++) — Amsterdam, 2026 Start",
  "description_raw": "…",
  "location_raw": "Amsterdam, Netherlands",
  "expect": {
    "role_family": "quant_dev",
    "seniority": "graduate",
    "min_years": null,
    "phd_required": false,
    "locations": [{"city": "Amsterdam", "country": "NL", "remote_mode": "onsite"}],
    "visa_sponsorship": "sponsors",
    "tech": ["cpp"],
    "languages_required": [],
    "compensation": {
      "amount_min": null, "amount_max": null, "currency": null, "period": null,
      "bonus_mentioned": false, "equity_mentioned": false
    },
    "closes_at": "2026-01-31T00:00:00Z"
  }
}
```

Deux champs n'existent pas dans `Posting` et servent uniquement à vérifier la
composition du corpus par du code plutôt qu'en relisant chaque entrée à l'œil :

- `company_slug` : renvoie vers `configs/companies.yaml`, utilisé pour le quota
  « 5 Software Engineer chez un prop shop » (il faut connaître le secteur).
- `lang` (ISO-639-1) : utilisé pour le quota « 10 offres en langue non anglaise ».

`locations` est toujours une liste, même à un seul élément : c'est ce qui
permet d'exprimer les offres multi-sites sans schéma différent.

`description_raw` est le texte de l'annonce tel que servi, **débarrassé de ses
balises HTML** pour que le fichier reste lisible et diffable en revue de code —
son contenu n'est ni reformulé ni résumé, seul le balisage est retiré.

## Ajouter une entrée

1. Copier l'offre réelle : `title_raw`, `description_raw`, `location_raw`, la source.
2. **Anonymiser** tout contact nominatif de recruteur. On archive du texte
   d'annonce, pas des données personnelles.
3. Remplir `expect` **à la main**, en lisant l'annonce. Ne jamais le remplir
   depuis la sortie du parseur : le corpus vérifierait alors que le code fait ce
   qu'il fait.
4. Un `null` attendu est une **assertion** (« l'annonce ne le dit pas »), pas une
   absence.

## Règle d'or

Le corpus est **figé** : on l'étend, on ne le régénère jamais. Un corpus
régénérable ne détecte aucune régression.

À chaque bug de parsing constaté : **l'entrée arrive ici avant le correctif**.
