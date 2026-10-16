# 0.3.19 (22) — réservation et paiement alignés sur le nouveau parcours du site

## Réservation et paiement

- La réservation depuis l'application passe désormais par le parcours du site
  Checkup Auto (`#reservation`) au lieu d'ouvrir directement l'ancien site
  Mercure `rdv.checkupauto.fr`.
- Le client profite ainsi du nouveau parcours de réservation et du paiement
  sécurisé hébergé par Mercure/Payline intégré au site, et des pages servies
  par le cache Cloudflare du site (ouverture plus rapide).
- Le parcours reste adapté à l'environnement : production sur
  `www.checkupauto.fr`, préproduction sur `test.checkupauto.fr`.
- Le bouton « Réserver un créneau » de l'accueil et l'accès réservation depuis
  l'espace client ouvrent tous les deux ce parcours du site.
- Les créneaux affichés restent les disponibilités Mercure en direct ; aucun
  rendez-vous n'est créé tant que le client n'a pas confirmé et payé sur le
  site.

## Qualification

L'application continue d'afficher le même espace client que le site, sans
seconde authentification. Les tests Swift, Xcode et de sécurité doivent être
verts sur la source exacte ; la préproduction `test.checkupauto.fr` doit être
déployée et vérifiée avant le nouvel envoi TestFlight par RemoteOps. Le
parcours de paiement hébergé Mercure/Payline reste un service réel : ne pas
créer de rendez-vous de test sur ce fournisseur sans accord explicite.
