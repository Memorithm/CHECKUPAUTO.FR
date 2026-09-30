# 0.3.10 (13) — préparation avant raccordement

- Environnement de préproduction signé, origine HTTPS fixe, badge visible.
- Séparation des identités Keychain, états APNs, véhicules, inventaire, cagnotte et acquittements entre production et préproduction. Les clés de production restent inchangées.
- Compte et scanner sur la préproduction. Saisie volontaire du lien de rattachement de test, sans lecture automatique du presse-papiers.
- Rejet des liens de rattachement provenant d’un autre environnement, contenant des identifiants ou un port différent.
- Test ActivityKit immédiat accessible dès iOS 17. Démarrage programmé uniquement dès iOS 26 ; les versions antérieures gardent les notifications locales et démarrent l’activité quand l’app est ouverte dans la fenêtre du rappel.
- Klaxons et présentation agrandie de 0.3.9 conservés.

La valeur par défaut du projet reste production. RemoteOps choisit explicitement preproduction pour cette livraison TestFlight et vérifie le marqueur dans les deux bundles signés. Aucun raccordement DNS ni envoi App Store public.

À vérifier sur iPhone : permission et son des notifications, Dynamic Island compacte/agrandie, rattachement d’un véhicule fictif et d’une cagnotte de test, modification/annulation du rendez-vous, fonctionnement hors ligne et effacement des données. Les liens de test doivent utiliser l’origine de préproduction ; les liens universels du domaine définitif seront validés après raccordement. Le fournisseur rdv.checkupauto.fr est réel, ne pas lui envoyer une réservation fictive.
