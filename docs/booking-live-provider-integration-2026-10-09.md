# Mercure VL: intégration et observations du 9 octobre 2026

## Sources consultées en lecture seule

Depuis le poste Thor autorisé, avec la session Mercure privée existante :

- `GET /admin/calendrier` déclare `resources: /admin/ligne_centre/json`.
- `GET /admin/ligne_centre/json` a retourné exactement une ressource : ligne 454,
  `typeVl=true`, `typePl=false`, `typeCl=false`, avec ses horaires.
- `POST /rech_dispon_rdv` est la recherche de disponibilités publique : les
  créneaux contiennent `heure` et `prix`, sans identifiant de ligne.
- Le nouveau lecteur non mis en cache a qualifié, sans le réserver, le créneau
  du 12 octobre 2026 à 09:00, prestation technique 1763, durée 40 minutes,
  tarif 8000 centimes. Il ne s'agit pas d'une réservation ni d'une garantie
  de disponibilité future.
- `POST /get_energie_prestation` est la lecture des énergies et options de
  paiement utilisée par le JavaScript public Mercure. Pour la prestation 1763,
  elle a retourné `paiementCentre=true`, `paiementWeb=false`.

Ces observations sont datées. Le code relit les sources au moment de la demande
et ne transforme pas ce document en preuve opérationnelle. Aucune donnée client,
aucun secret et aucun contenu de session n'est enregistré dans ce document.

## Raccordement effectué

La route HTTP authentifiée transmet la date et l'heure au contexte serveur.
Celui-ci charge la politique de paiement depuis Mercure, non depuis le navigateur.
Le résolveur lie le catalogue administratif à la ressource et au créneau.
Le passage à l'exécuteur refait la lecture du créneau : date, heure, prestation,
ligne, durée, tarif et ancienneté de la preuve sont contrôlés avant écriture.
Une preuve de plus de 60 secondes ou un tarif modifié bloque l'opération.
Les champs dynamiques du writer sont issus de ces sources, et non d'options
HTML inexistantes.

Le rapprochement ligne/créneau est volontairement limité à une unique ressource
exclusivement VL. Plusieurs lignes, des types mixtes ou une réponse ambiguë
bloquent l'opération ; aucun premier élément n'est choisi arbitrairement.

## Non livré / non autorisé par ces observations

Le paiement en ligne est indisponible dans la réponse fournisseur observée.
Le paiement en centre ne remplace pas automatiquement le parcours en ligne.
Le connecteur de reçu Mercure vérifié pour cette nouvelle réservation reste à
raccorder ; l'absence de reçu ne peut jamais produire un paiement confirmé.

Les drapeaux de production demeurent désactivés. Aucun rendez-vous réel n'a été
créé, aucun paiement exécuté, aucune suppression, bascule DNS ou mise en
production effectuée. La recette création–relecture–anti-doublon–suppression
et les notifications restent à qualifier après résolution des prérequis.

Les tests de composition utilisent des fixtures explicites. Ils valident le
raccordement et les refus ; ils ne constituent pas une homologation réelle.
