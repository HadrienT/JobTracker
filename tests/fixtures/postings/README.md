# Corpus doré

Une offre **réelle** par ligne dans `corpus.jsonl`, avec ses champs attendus
étiquetés à la main. C'est la vérité terrain du normaliseur (WP03) et du matcher
(WP05), et la seule mesure de progrès du projet.

Format et règles : [`blueprint/08-TESTING.md`](../../../blueprint/08-TESTING.md) §2.
Quotas de composition à atteindre : [`blueprint/wp/WP00-recon-registry.md`](../../../blueprint/wp/WP00-recon-registry.md) §4.

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
