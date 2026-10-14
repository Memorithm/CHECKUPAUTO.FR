# 0.3.15 (18) — espace client identique au site et guidage GPS

Build TestFlight interne de préproduction.

## Espace client

L'option « Espace client » reprend directement le tableau de bord actuel
`test.checkupauto.fr/compte`, avec **exactement le même code HTML, CSS et JavaScript** :

- En-tête et profil client, informations de contact.
- Rapports de contrôle technique, import de photo/PDF, export de l'analyse.
- Fidélité, cagnotte, parrainage et actions associées.
- **Mes véhicules** : cartes SIV/FNI, immatriculation et numéro de formule ou date
  d'établissement, boutons pleine largeur « Réserver un contrôle », « Modifier »,
  « Supprimer », et formulaire de carte grise avec photos explicatives.
- Actions de compte et confirmations de suppression actives.

La vue est intégrée par WebKit dans l'application, sans barres Safari. Une
session de site indépendante, temporaire, `HttpOnly` et `Secure` est créée à
partir de la session iOS déjà validée. La connexion Apple/Google/e-mail n'est pas
redemandée. Le navigateur éphémère n'a jamais accès au jeton Keychain natif.

## Itinéraire

« Itinéraire vers le centre » est accessible depuis le tableau de bord et
l'espace client. Choix de l'application installée (Plans Apple, Google Maps,
Waze) ou partage à une autre application GPS.

Adresse : 1E rue Niépce, 78130 Les Mureaux.
Point d'arrivée identique au site : latitude 48.980120, longitude 1.890251.
Aucune lecture ni transmission automatique de la position de l'utilisateur.

## Sortie volontaire

La réservation quitte la vue client vers le planning Mercure
`https://rdv.checkupauto.fr/`. L'ouverture d'une application GPS est
déclenchée uniquement après sélection volontaire. Les autres liens restent
dans l'application ou sont bloqués.

## Qualification

- Test du backend `POST /api/mobile/auth/web-session` et de la durée de vie
  du cookie ; aucune clé native dans la vue web ou les journaux.
- Contrôle des cartes, boutons, validations carte grise et du parcours GPS.
- CI Xcode Swift/iOS et Security CI du commit exact.
- Déploiement du backend de préproduction via RemoteOps, vérification HTTPS,
  puis archive/signature/upload Apple de 0.3.15 (18).
- Validation Apple `VALID` et association au groupe « CheckupAuto — Test interne ».

L'archive de préproduction n'est pas destinée à l'App Store public.
