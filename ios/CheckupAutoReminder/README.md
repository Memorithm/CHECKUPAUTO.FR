# Checkup Auto Reminder iOS

Application SwiftUI local-first pour les rappels de contrôle technique.

## V0.3 préparée

- ajout manuel d’un ou plusieurs véhicules ;
- stockage local des échéances ;
- notifications J-60, J-30, J-15, J-7 et J-1 à 09:00 Europe/Paris, locales tant que le canal push central n’est pas activé ;
- reprogrammation des rappels au lancement ;
- synchronisation de la politique publique (J-60/J-30/J-15/J-7/J-1, heure, fuseau et URL de réservation) depuis `/api/mobile/bootstrap`, avec repli local sûr ;
- suppression des notifications associées lorsqu’un véhicule est supprimé ;
- accès direct à la réservation Checkup Auto ;
- tableau de bord SwiftUI clair et premium avec prochaine échéance prioritaire ;
- accès direct à l’espace client particulier/pro et au scan de rapport CT ;
- affichage natif de la cagnotte fidélité vérifiée et des véhicules rattachés à Mercure ;
- navigation vers l’analyse chiffrée des rapports CT (PDF/JPEG/PNG → Markdown + conseils) via le compte authentifié ;
- tests unitaires du calcul des échéances ;
- Live Activities / Dynamic Island pour le parcours court autour d’un rendez-vous de contrôle technique ;
- activité J-1 à 18:00 puis activité jour J deux heures avant le rendez-vous, à partir de l’horaire Mercure vérifié ;
- rappel visible « Pensez à votre carte grise » et ouverture ciblée de l’app depuis la Dynamic Island ;
- planification idempotente et réconciliation si l’horaire du rendez-vous change ;
- pipeline de livraison TestFlight piloté par GitHub Actions via le Mac mini, avec numéro de build unique.

L'application synchronise au serveur uniquement un `deadlineId` UUID opaque et la date d'échéance. L'immatriculation et le libellé du véhicule restent sur l'iPhone ; aucun identifiant Mercure ni aucune donnée client n'est transmis par cette API. L'instantané est authentifié par l'identité d'installation conservée dans le Trousseau Apple.

Le bootstrap public indique si le push central est réellement actif. Tant qu'il ne l'est pas, les notifications locales restent le mécanisme de repli ; lorsqu'il est activé, l'application retire les notifications locales correspondantes afin d'éviter les doublons.

## Préflight Release reproductible

Avant d’ouvrir Xcode, le serveur peut contrôler de façon déterministe le bundle ID, la configuration Release APNs, les entitlements, Associated Domains/AASA, le préfixe Apple, `/app`, les supports QR et l’état TestFlight/App Store :

```bash
python3 -m unittest ios_release_preflight_test.py
python3 - <<'PY'
import json
import ios_release_preflight
print(json.dumps(ios_release_preflight.status({"seo":{"canonicalUrl":"https://www.checkupauto.fr/"}}), indent=2))
PY
```

Les secrets de signature, APNs et OAuth restent exclusivement hors Git. Un préflight `degraded` signale une incohérence du projet ; `configuration_required` indique notamment un préfixe Apple manquant ; `blocked_external` signifie que le projet est cohérent mais qu’aucun canal TestFlight/App Store n’est encore publié.

## Runner Release macOS

La chaîne automatisée `xcodegen → XCTest → archive signée → validation des entitlements → export` est documentée dans [`docs/ios-release.md`](../../docs/ios-release.md). Le runner `ios_release_runner.py` refuse toute Release réelle hors de `main`, sur un arbre sale ou sur un commit différent de `origin/main`, et garde tous les identifiants Apple hors Git.

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
