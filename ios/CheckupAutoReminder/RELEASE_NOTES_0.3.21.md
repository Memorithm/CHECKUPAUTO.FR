# Checkup Auto — 0.3.21 (24)

## Paiement : consignes impossibles à manquer

Juste avant l'ouverture du paiement Payline, l'application affiche désormais un
écran d'avertissement animé, très visible :

- **« Ne fermez pas l'application »**, bien en évidence, dans un encadré qui
  clignote (l'animation est remplacée par un affichage fixe à fort contraste si
  l'option « Réduire les animations » d'iOS est active).
- Rappel clair qu'après un paiement validé, il faut **revenir sur
  l'application** : le rendez-vous s'y confirme alors automatiquement.
- Le paiement par carte Payline ne s'ouvre qu'après le passage sur cet écran.

La même consigne « ne fermez pas / revenez sur cette page » clignote aussi sur
la page du site pour le parcours web.

## Choix du créneau

- Le planning natif permet maintenant d'**afficher plus de créneaux** : si la
  première période est complète, un bouton charge les jours suivants (jusqu'à
  l'horizon de réservation du centre) au lieu de renvoyer vers le téléphone.

## Corrections

- Le bouton « Réserver » d'un rappel ouvre bien le parcours, même lorsque
  l'application était fermée (démarrage à froid) : l'intention est mémorisée
  jusqu'à l'affichage de l'espace client.

Mercure et Payline inchangés. test.checkupauto.fr est servi via le cache
Cloudflare Pages.
