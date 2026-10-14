# 0.3.16 (19) — véhicules partagés et dates françaises

Nouvelle version TestFlight interne de préproduction, succédant au build
0.3.15 (18) confirmé `VALID` et disponible dans le groupe interne.

## Mes véhicules — site et iOS

- Les véhicules enregistrés dans le compte authentifié sont affichés à partir
  du même inventaire serveur sur le site et dans l'application.
- L'espace client du site reste intégré par WebKit, avec une session navigateur
  éphémère, sécurisée, distincte du bearer Keychain.
- Les cartes de véhicule possèdent un menu à trois points avec les opérations
  de modification et suppression, dans le site et le tableau de bord iPhone.
- Après fermeture du compte intégré, l'application recharge les véhicules du
  compte pour refléter les changements effectués.

## Véhicules locaux plus anciens

Les véhicules/rappels créés uniquement sur l'iPhone sont marqués
« non synchronisés ». Une action explicite « Associer à mon compte » permet
de préremplir l'immatriculation. L'utilisateur doit ensuite fournir les
données du certificat (numéro de formule SIV ou date FNI), ainsi que les
caractéristiques du véhicule avant enregistrement.

Il n'y a **aucune importation automatique** ni suppression des rappels
locaux ; les secrets de carte grise ne sont pas conservés en clair sur l'iPhone.
La liste du compte repose sur les API authentifiées existantes.

## Affichage localisé

Le grand bandeau « Prochain contrôle » utilise explicitement le français :
« 14 octobre 2027 » et non « 14 October 2027 », indépendamment de la
langue configurée sur l'appareil.

## Livraison

Contrôles CI Swift, simulateur Xcode, sécurité et interface web requis sur
le commit exact, puis déploiement serveur préalable via Memorithm/RemoteOps.
Livraison signée et publiée uniquement par le pipeline TestFlight contrôlé
sur le Mac mini, avec un manifeste de blobs Git épinglé. La présence de cette
note ou d'une PR ne constitue pas une preuve de livraison Apple.
