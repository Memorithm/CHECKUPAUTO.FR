# Réservation Web CheckupAuto : paiement avant confirmation Mercure

**Statut au 14 octobre 2026 : conception de sécurité et première brique
logicielle. Aucun parcours de paiement-avant-réservation n'est actif.**

## Deux canaux volontairement distincts

- **iOS** : conserver provisoirement le bouton « Réserver un contrôle » vers
  `https://rdv.checkupauto.fr`. Aucun changement des liens natifs dans cette
  tranche.
- **Web** : viser un parcours hébergé par CheckupAuto : choix de la prestation,
  disponibilité réelle, identité et véhicule, consentements, règlement, statut
  puis confirmation Mercure. La page hébergée de l'acquéreur Payline / Monext
  est une étape bancaire distincte, pas une redirection vers MercureWeb.

La page `/go/booking` délègue encore vers Mercure lorsque son activation et
son homologation manquent. **Ne pas activer par un changement de drapeau seul.**

## Problème réel du code préexistant

- `customer_booking_create_api.create` refuse désormais une écriture Mercure
  sans paiement déjà vérifié.
- `customer_booking_payment_start.start` requiert au contraire un
  `providerReference` de rendez-vous Mercure déjà confirmé.
- `assets/booking-journey.js` appelle `/booking/create` avant
  `/booking/payment/start` ; la dépendance est circulaire.
- `payment_payline.do_web_payment_xml` utilise `action=101` (paiement
  immédiat). `payment_payline.parse_details_response` classe actuellement
  `ACCEPTED` comme `captured`, sans distinguer une autorisation seule.

Ces éléments ne sont **pas** une preuve de fonctionnement du paiement réel.

## Ordre cible sûr : autoriser, réserver, capturer

1. **Préparer le devis** : le serveur lit les prestations, tarif, date, heure et
   preuve du créneau Mercure. Il exige le compte connecté, le véhicule autorisé,
   la signature d'intention navigateur, l'acceptation persistante des CGV
   publiées et la clé d'idempotence. Aucun prix, consentement, preuve bancaire
   ou autorisation Mercure n'est fourni par le navigateur.
2. **Préautoriser chez Payline** : `doWebPayment`, code action **100**,
   uniquement après homologation du contrat. La transaction ne doit PAS être
   considérée capturée parce que son `shortMessage` est `ACCEPTED`.
   `getWebPaymentDetails` doit authentifier la correspondance exacte entre
   compte, paiement, montant, devise, clé de demande et référence Payline.
3. **Requalifier le créneau** (délai très court) : refaire la lecture non
   cachée de Mercure, vérifier la ligne VL, l'opérateur, la prestation,
   l'horaire, la durée et le montant (dont promotions). Si le prix ou le
   créneau a changé, **ne pas écrire**, ne pas capturer ; annuler l'autorisation
   par un mécanisme qualifié et ouvrir un suivi de rapprochement.
4. **Écrire une seule fois** dans Mercure : journal durable déjà existant
   `customer_booking_journal`, état « reconciliation_required » persisté
   *avant* le POST du formulaire complet `/admin/rendez_vous_add`. Le
   connecteur ne peut être appelé que depuis RemoteOps / serveur autorisé.
5. **Relire indépendamment** le rendez-vous : identité canonique, date,
   créneau, prestation, client et véhicule. Réponse réseau ambiguë = lecture
   et investigation, **jamais** de nouveau POST aveugle.
6. **Capturer le paiement** : seulement après confirmation Mercure,
   `doCapture` action **201** et vérification bancaire de capture. Capture
   ambiguë = rapprochement, pas de seconde tentative aveugle.
7. **Afficher le résultat exact** : « réservé et payé » seulement si les deux
   preuves existent. Tant que capture ou écriture sont incertaines, afficher
   « vérification en cours » avec recours humain, sans présenter un succès.

Une autorisation n'est pas une réservation et une réservation n'est pas une
capture. Le client n'a pas à ressaisir ses informations dans Mercure.

## Première brique implémentée dans cette tranche

`customer_booking_prepayment_quote.prepare_quote` réalise uniquement la
préparation du devis **avant** tout appel Payline : intention signée valide
moins de 48 h, créneau et prestation égaux à l'intention, preuve CGV
préexistante lue sans la fabriquer, exigence de performance immédiate, nouvelle
lecture serveur du prix et du véhicule, référence bancaire pseudonymisée liée
au compte et à la clé de demande, puis préparation du journal idempotent.

Le lecteur `compliance_store.checkout_acceptance_for_token` n'écrit aucun
consentement. Aucun endpoint n'appelle encore `prepare_quote`, aucun
paiement n'est lancé et aucune création Mercure n'est modifiée. Cette tranche
ne doit PAS être annoncée comme « réservation Web opérationnelle ».

## Conditions de livraison manquantes

- Homologuer `doWebPayment(action=100)`, `getWebPaymentDetails`,
  `doCapture(201)`, annulation `doReset`, comportements 3-D Secure, et
  états autorisé/capturé distincts dans le ledger, en sandbox d'abord.
- Relier un endpoint authentifié, CSRF, idempotent et limité en débit à ce
  devis ; refuser les montants et références introduits par le navigateur.
- Conserver de manière privée et gouvernée le lien entre intention, Payline
  et notification pour reprise après fermeture navigateur ou perte de session.
- Vérifier la disponibilité et le prix lors du dernier passage, **avant**
  l'écriture Mercure ; qualifier création/relecture et la politique
  d'annulation/no-show du fournisseur.
- Traitement des paiements autorisés sans rendez-vous, rendez-vous confirmé
  sans capture, erreurs de notification, remboursements et rapprochement humain.
- Vérifier les paramètres live Payline dans le coffre privé, les preuves
  d'acceptation bancaire et d'homologation Mercure, puis obtenir une recette
  de bout en bout sans vrais débits ni faux rendez-vous commerciaux.
- CI sur le SHA exact, validation multi-navigateurs, déploiement épinglé via
  RemoteOps et test iOS séparé. Ne jamais contourner la garde CHECKUPAUTO.

## Documentation fournisseur

- Monext Online, *Codes – Action* (21 septembre 2022) :
  https://docs.monext.fr/spaces/DT/pages/747146896/Codes+-+Action
  (100 = autorisation seule ; 101 = autorisation et capture).
- Monext Online, *Le paiement à l'expédition* (4 août 2022) :
  https://docs.payline.com/spaces/DT/pages/747145106/Cas+d+utilisation+-+Le+paiement+%C3%A0+l+exp%C3%A9dition
  (action 100 puis `doCapture` action 201).
- Monext Online, *getWebPaymentDetails* (16 mai 2025) :
  https://docs.monext.fr/spaces/DT/pages/747144852/Webservice+-+getWebPaymentDetailsRequest
  (relecture obligatoire du résultat de la session web).

