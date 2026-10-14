# Checkup Auto 0.3.17 (20) — espace client simplifié et prochaine échéance

Version TestFlight interne, basée sur les corrections de l'espace client
CHECKUPAUTO.FR PR #721.

## Espace client intégré au site et à l'application

La page client affiche maintenant une carte **Rendez-vous** avec uniquement
le lien « Réserver un contrôle ». Elle n'affiche plus les sections Fidélité,
Parrainage, Rapport de contrôle technique ni le lien « Consulter mes
rendez-vous Mercure ». Ces modifications concernent le rendu du compte, 
pas une suppression des données historiques.

## Date du prochain contrôle obligatoire

Tout nouveau véhicule ajouté depuis la page web du compte ou depuis iOS
nécessite une date de prochain contrôle. Une validation côté serveur interdit
une date absente, nulle, invalide ou un format ambigu. L'utilisateur iOS doit
confirmer explicitement la date choisie avant de pouvoir enregistrer.

La date (stockée au format canonique AAAA-MM-JJ) est liée à l'enregistrement
chiffré du véhicule et renvoyée aux deux interfaces. L'application recharge
la date du compte, la répercute sur ses rappels locaux lorsqu'ils existent,
et conserve les véhicules précédemment enregistrés sans date afin de
permettre leur correction.

## Dates en français

Le bandeau « Prochain contrôle », les fiches véhicules et les rappels
utilisent **JJ/MM/AAAA** et **JJ/MM/AAAA à HH:mm**. Les sélecteurs iOS
emploient la locale française. Les champs de certificat d'immatriculation
restent distincts de la date du prochain contrôle.

## Contrôle de livraison

La signature et la publication s'effectuent uniquement par RemoteOps
depuis le Mac mini sur un manifeste de fichiers Git épinglé au SHA source,
après validation de l'API sur `https://test.checkupauto.fr`.
La fusion de cette note n'est pas une preuve de livraison Apple.
