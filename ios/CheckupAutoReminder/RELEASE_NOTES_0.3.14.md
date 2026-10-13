# 0.3.14 (17) — compte natif, session persistante et carte grise

Version candidate de préproduction pour le groupe TestFlight interne.

- **Espace client 100 % natif** : le bouton et l’icône Compte n’ouvrent plus `/compte` et ne demandent plus une seconde connexion web après Apple, Google ou e-mail.
- **Session conservée au retour dans l’application** : une indisponibilité réseau temporaire ne provoque plus une déconnexion ; le jeton de session reste dans le trousseau iOS. Une session effectivement expirée reste invalidée côté serveur.
- **Google** : le parcours OAuth reste dans la fenêtre sécurisée d’iOS avec PKCE, et retourne à l’application ; la confirmation du domaine imposée par iOS est explicitement expliquée. Pas de navigateur externe pour les liens d’aide et de confidentialité.
- **Ajout de véhicule** : saisie SIV/FNI avec contrôle des formats, numéro de formule SIV ou date d’établissement de la carte grise FNI, deux images explicatives utilisées sur le site, marque/modèle/énergie provenant du catalogue Mercure, sauvegarde dans le compte authentifié.
- **Rappels locaux** : l’échéance de contrôle technique reste distincte de la date du certificat et peut être programmée sur cet iPhone.
- **Réservation Mercure** : l’accès direct à `https://rdv.checkupauto.fr` est conservé.

## Conditions de livraison

Le backend `test.checkupauto.fr` doit d’abord exposer les routes mobiles authentifiées de profil et de véhicule. La publication TestFlight exige ensuite le snapshot Git exact, la signature Apple sur le Mac mini, un upload unique de 0.3.14 (17), la validation Apple et l’association au groupe « CheckupAuto — Test interne ».

Cette version de préproduction ne constitue pas une publication App Store publique.
