# 0.3.18 (21) — ouverture plus rapide de l'espace client

## Espace client dans l'application

- Préparation anticipée de la session WebKit après connexion native, sans bloquer
  l'écran d'accueil.
- Réutilisation du cookie web sécurisé encore valide au lieu de demander une
  nouvelle session à chaque ouverture du compte.
- Une seule création de session si le client ouvre le compte pendant la
  préparation en cours.
- Invalidation immédiate du cache mémoire à la déconnexion, au changement de
  compte ou à l'expiration de la session.
- Le cookie reste HttpOnly, Secure et installé dans un WKWebView éphémère :
  aucun jeton natif n'est exposé au JavaScript ou stocké dans les préférences.

## Véhicules

- Le formulaire de date du prochain contrôle technique accepte huit chiffres
  sans saisie des barres obliques. Exemple : 14102027 devient 14/10/2027.
- La date reste obligatoire et vérifiée côté serveur ; les fiches véhicules
  et rappels existants sont conservés.

## Qualification

L'application continue d'afficher le même espace client que le site, sans
seconde authentification. Les tests Swift, Xcode et de sécurité doivent être
verts sur la source exacte ; la préproduction doit être déployée avant le
nouvel envoi TestFlight par RemoteOps. Les temps d'ouverture réels sur iPhone
restent à mesurer après publication.
