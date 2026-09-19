# Checkup Auto Reminder iOS

Application SwiftUI local-first pour les rappels de contrôle technique.

## V1 préparée

- ajout manuel d’un ou plusieurs véhicules ;
- stockage local des échéances ;
- notifications locales J-60, J-30, J-15, J-7 et J-1 à 09:00 heure locale ;
- reprogrammation des rappels au lancement ;
- suppression des notifications associées lorsqu’un véhicule est supprimé ;
- accès direct à la réservation Checkup Auto ;
- tests unitaires du calcul des échéances.

La synchronisation Mercure ne doit pas exposer de données clients via une API publique. Elle sera branchée ensuite derrière l’authentification Checkup Auto et le moteur de relance central.

## Première compilation sur le Mac mini

Dans Terminal, depuis ce dossier :

```bash
brew install xcodegen
xcodegen generate
open CheckupAutoReminder.xcodeproj
```

Dans Xcode, sélectionner l’équipe Apple de signature, puis exécuter d’abord les tests sur un simulateur iPhone avant le test sur un iPhone physique.

Le projet demande iOS 17 ou supérieur et ne dépend d’aucune bibliothèque tierce à l’exécution.

## ReferralWallet et moteur central

Le solde de parrainage ne sera jamais calculé localement par l’application. `referral_engine.py` reste la source de vérité serveur pour les crédits en attente, acquis et consommés. L’application affichera ce solde après mise en place de l’authentification Checkup Auto.

La politique locale de rappel doit rester alignée avec `reminder_engine.py` : J-60, J-30, J-15, J-7 et J-1 à 09:00 dans le fuseau local.
