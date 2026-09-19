# Checkup Auto Reminder iOS

Application SwiftUI local-first pour les rappels de contrôle technique.

## V1 préparée

- ajout manuel d’un ou plusieurs véhicules ;
- stockage local des échéances ;
- notifications J-60, J-30, J-15, J-7 et J-1 à 09:00 Europe/Paris, locales tant que le canal push central n’est pas activé ;
- reprogrammation des rappels au lancement ;
- synchronisation de la politique publique (J-60/J-30/J-15/J-7/J-1, heure, fuseau et URL de réservation) depuis `/api/mobile/bootstrap`, avec repli local sûr ;
- suppression des notifications associées lorsqu’un véhicule est supprimé ;
- accès direct à la réservation Checkup Auto ;
- tests unitaires du calcul des échéances.

L'application synchronise au serveur uniquement un `deadlineId` UUID opaque et la date d'échéance. L'immatriculation et le libellé du véhicule restent sur l'iPhone ; aucun identifiant Mercure ni aucune donnée client n'est transmis par cette API. L'instantané est authentifié par l'identité d'installation conservée dans le Trousseau Apple.

Le bootstrap public indique si le push central est réellement actif. Tant qu'il ne l'est pas, les notifications locales restent le mécanisme de repli ; lorsqu'il est activé, l'application retire les notifications locales correspondantes afin d'éviter les doublons.

## Première compilation sur le Mac mini

Dans Terminal, depuis ce dossier :

```bash
brew install xcodegen
xcodegen generate
open CheckupAutoReminder.xcodeproj
```

Dans Xcode, sélectionner l’équipe Apple de signature, puis exécuter d’abord les tests sur un simulateur iPhone avant le test sur un iPhone physique.

Pour tester une build Debug contre un environnement CheckupAuto temporaire sans modifier le code, définir la variable d’environnement du scheme CHECKUPAUTO_API_BASE_URL avec une origine HTTPS de test. Seules les origines HTTPS propres sont acceptées (sans identifiants, chemin, query string ni fragment). En Release, cette variable est ignorée et l’API reste verrouillée sur https://www.checkupauto.fr.

Le projet demande iOS 17 ou supérieur et ne dépend d’aucune bibliothèque tierce à l’exécution.

Sans Xcode complet, le Mac mini peut néanmoins valider le noyau déterministe du planificateur avec les Command Line Tools :

```bash
swiftc Sources/Models.swift Tests/ReminderPlanSmoke.swift -o /tmp/reminder-plan-smoke
/tmp/reminder-plan-smoke

swiftc Sources/MobileBootstrap.swift Tests/MobileBootstrapSmoke.swift -o /tmp/mobile-bootstrap-smoke
/tmp/mobile-bootstrap-smoke

swiftc Sources/Models.swift Sources/DeviceRegistration.swift Sources/MobileDeadlineSync.swift Tests/MobileDeadlineSyncSmoke.swift -o /tmp/mobile-deadline-sync-smoke
/tmp/mobile-deadline-sync-smoke
```

Les sorties attendues sont `REMINDER_PLAN_SMOKE_OK`, `MOBILE_BOOTSTRAP_SMOKE_OK` et `MOBILE_DEADLINE_SYNC_SMOKE_OK`. Les tests XCTest et la compilation iOS complète nécessitent Xcode.app.

## ReferralWallet et moteur central

Le solde de parrainage ne sera jamais calculé localement par l’application. `referral_engine.py` reste la source de vérité serveur pour les crédits en attente, acquis et consommés. L’application affichera ce solde après mise en place de l’authentification Checkup Auto.

La politique locale de rappel est pilotée par `/api/mobile/bootstrap`, lui-même dérivé de `reminder_engine.py` : J-60, J-30, J-15, J-7 et J-1 à 09:00 Europe/Paris par défaut.
