# 0.3.11 (14) — réservation depuis l’application

Le bouton Réserver ouvre le parcours CheckupAuto dans le navigateur sécurisé intégré à l’app, avec sa barre d’adresse visible. La destination est construite à partir d’une origine HTTPS fixe ; aucun certificat invalide n’est accepté par une logique personnalisée.

En production : https://www.checkupauto.fr/?source=ios-app#reservation, choix du créneau et parcours du site. En préproduction : https://stage.179.198.210.187.sslip.io/payment/test?source=ios-app, réservation fictive et paiement sandbox explicitement identifiés. Les actions Réserver des notifications utilisent le même routage ; iOS peut ouvrir ce lien dans Safari depuis une notification.

Le paiement bancaire est hébergé par Payline / Monext, jamais par un formulaire natif qui stocke des données de carte. L’accès réel dépend de la configuration bancaire et de sa recette d’homologation. Le certificat HTTPS protège le transport ; le résultat bancaire doit également être relu et vérifié côté serveur. Aucune activation d’encaissement réel ni raccordement DNS par cette version.
