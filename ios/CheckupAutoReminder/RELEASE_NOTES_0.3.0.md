# Checkup Auto iOS 0.3.0

## Dynamic Island et Live Activities
- Ajout d’une extension WidgetKit / ActivityKit dédiée aux rendez-vous de contrôle technique.
- Première activité planifiée la veille à 18:00.
- Deuxième activité planifiée le jour J, deux heures avant le rendez-vous.
- Message de préparation : « Pensez à votre carte grise ».
- Appui sur la Live Activity : ouverture de l’app et acquittement du rappel concerné uniquement.
- Réconciliation des activités lorsque l’horaire du rendez-vous est modifié.

## Rendez-vous Mercure
- L’horaire du prochain contrôle technique est lu côté serveur depuis Mercure.
- Le rapprochement est effectué sur une identité véhicule/client déjà vérifiée.
- L’iPhone reçoit uniquement un binding opaque et l’horodatage du rendez-vous.
- Aucun identifiant de rendez-vous Mercure n’est exposé à l’application.
- Une modification d’identité de rattachement invalide l’ancien rendez-vous mis en cache.

## Distribution
- Ajout d’un pipeline GitHub Actions → Mac mini → archive Release → App Store Connect.
- Les identifiants App Store Connect restent hors Git et sont installés temporairement pendant la livraison.
- Chaque upload TestFlight reçoit un numéro de build unique.
- Le branchement physique de l’iPhone n’est plus nécessaire pour les builds distribuées par TestFlight.

## Compatibilité
- Le tableau de bord premium, la cagnotte, les véhicules liés à Mercure, les rappels classiques et les parcours compte / rapport CT restent disponibles.
- Les notifications locales et APNs continuent de servir de mécanismes de rappel en dehors des Live Activities.
