# Checkup Auto — 0.3.20 (23)

## Réservation entièrement dans l'application

La prise de rendez-vous se déroule désormais sans quitter l'application et sans
seconde connexion.

- **Choix du créneau en natif** : la prestation, les jours et les heures sont
  lus en direct depuis le planning Mercure (API `/api/booking/services` et
  `/api/booking/availability`), servies via le site connecté à Cloudflare Pages.
  Le premier écran s'affiche immédiatement, sans chargement de page web.
- **Suite du parcours dans l'application** : véhicule, coordonnées puis
  récapitulatif Mercure s'ouvrent dans la vue web signée de l'application, avec
  la session déjà ouverte (cookie court et chiffré). L'utilisateur n'a plus à se
  reconnecter après avoir ouvert son espace client.
- **Paiement Payline uniquement en fenêtre** : seule la page de paiement par
  carte s'ouvre dans une fenêtre dédiée, puis se referme automatiquement dès que
  le paiement est confirmé ou annulé. Le reste reste dans l'application.
- **Accueil, espace client et notification** : les trois points d'entrée
  ouvrent ce même parcours natif.

## Performances

- Préchargement de la session sécurisée et du planning dès l'écran d'accueil.
- test.checkupauto.fr est servi via le cache Cloudflare Pages.

TestFlight : préproduction sur test.checkupauto.fr, build déclenché depuis
RemoteOps.
