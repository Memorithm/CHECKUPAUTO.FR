# Réservation entièrement sur Checkup Auto — contrat produit

Statut : architecture cible, **non déployée et non qualifiée en production**.

## Règle non négociable

Le client reste sur le site Checkup Auto pour sélectionner une prestation, choisir un créneau, se connecter, renseigner ou sélectionner son véhicule, accepter les CGV, régler si nécessaire et consulter la confirmation. Il n'existe plus de redirection du parcours de réservation vers `rdv.checkupauto.fr`. Mercure reste l'autorité métier pour la disponibilité, les réservations et leur statut.

## Parcours

1. Le site lit les prestations, disponibilités et prix auprès de Mercure. Les créneaux ne sont pas présentés comme bloqués avant confirmation par le fournisseur.
2. Une session client authentifiée et vérifiée est obligatoire ; les données du véhicule sont validées côté serveur, et le numéro de formule n'est jamais affiché intégralement dans les récapitulatifs.
3. Le client revoit prestation, prix final, date, heure, véhicule et CGV, puis confirme.
4. Le serveur crée une intention idempotente liée à l'identité client, au véhicule, à la prestation et au créneau, puis effectue l'opération métier autorisée via un connecteur Mercure qualifié. Toute réponse ambiguë est réconciliée auprès de Mercure avant une nouvelle tentative. Ne jamais créer une seconde réservation aveuglément.
5. **Le rendez-vous est écrit dans Mercure avant le paiement.** Dès que Mercure l'a confirmé (relecture indépendante), le client est envoyé vers la page de paiement hébergée Payline / Monext de Checkup Auto (`POST /api/customer/booking/payment/start`, qui n'accepte que la clé de la demande). Le montant et la référence viennent du serveur : prix relu dans Mercure avant l'écriture, référence du rendez-vous, preuve CGV rattachée. Une fermeture de popup ou un retour navigateur n'est pas une preuve de paiement. En attendant l'API de paiement Mercure, Payline reste le seul encaissement en ligne.
6. Au retour de Payline, le serveur relit le paiement (`getWebPaymentDetails`), puis renvoie le client vers `/compte/reservation?cle=…`. Cette page affiche « réservé, paiement à effectuer » avec un bouton « Payer maintenant », ou « confirmé et payé » une fois le paiement vérifié. Ne pas envoyer de confirmation de paiement au client avant cet état.
7. Les annulations, expirations et échecs de paiement sont réconciliés sans doublons, et le client reçoit une information explicite sur l'état réel. **Non livré à ce stade :** l'annulation automatique dans Mercure d'un rendez-vous resté impayé. Il faut un connecteur d'annulation qualifié ; en attendant, ces rendez-vous restent visibles dans le planning et se traitent manuellement.

## Contraintes de mise en œuvre

- Le mode `mercureweb-delegated` et `booking_bridge.auto_submit_html` sont des mécanismes **hérités à remplacer**, non la cible de production.
- `booking_test.create_appointment` et `mercure_admin_client.create_synthetic_test_appointment` concernent uniquement des rendez-vous synthétiques : **interdiction de les réutiliser comme création de réservation client réelle**.
- La lecture des disponibilités `mercure_public_client.availability` n'accorde aucun droit d'écriture.
- Le connecteur de création réelle et l'intégration du paiement doivent être qualifiés sur une API fournisseur documentée ou un contrat contrôlé du PC Mercure ; pas d'accès public direct à MySQL, RDP, SMB, WinRM ou aux secrets.
- Le paiement, la confirmation métier et la notification doivent disposer de preuves serveur indépendantes et d'un journal idempotent, avec protections contre CSRF, rejeu, fraude, courses concurrentes et doubles débits.
- Pas de bascule DNS ni de redirection publique avant essais de bout en bout réussis en préproduction.

## Critères d'acceptation

- Tests navigateurs mobiles et desktop : aucun départ du domaine pendant le parcours.
- Parcours nouveau véhicule SIV, FNI et véhicule enregistré ; refus des identifiants invalides.
- Créneau indisponible, double clic, timeout Mercure, reconnexion et nouvelle tentative : aucune réservation en double.
- Paiement non requis : confirmation interne après vérification Mercure.
- Paiement requis : rendez-vous écrit dans Mercure, puis page Payline hébergée, retour sur Checkup Auto et confirmation côté serveur. Échec, abandon et 3-D Secure sont traités ; « Payer maintenant » reste disponible tant que le paiement n'est pas vérifié.
- Test réel contrôlé avec un rendez-vous synthétique créé, relu et supprimé dans Mercure, puis test d'homologation paiement sans débit bancaire.
- Aucun résultat de test synthétique ne doit être présenté comme une réservation client réelle.
