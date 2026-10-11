# Réservation sur le site : vue d'ensemble et activation

Le parcours de réservation sur checkupauto.fr est livré **désactivé**. Sans action explicite, `/go/booking` produit exactement la page de redirection déléguée vers MercureWeb. Le test `go_booking_delegated_regression_test.py` le vérifie : il compare l'empreinte SHA-256 de la page à celle produite par `origin/main` avant ces changements.

Documents détaillés :

- `reservation-sur-site-1-disponibilite.md` : interrupteur, capacités déclarées, preuve de validation signée.
- `reservation-sur-site-2-notifications.md` : champs de notification Mercure (e-mail, impression, SMS).
- `reservation-sur-site-3-vehicule.md` : correspondance du modèle Mercure et option « Autres modèles ».
- `reservation-sur-site-4-observabilite.md` : santé de la session Mercure, échecs d'écriture, alertes.

## Parcours (quand tout est ouvert)

1. Le client choisit un créneau, puis valide le passage par son espace client, comme aujourd'hui.
2. `/go/booking` affiche un **récapitulatif sur le site** : prestation, tarif, créneau, client, véhicule et consentements. Les textes CGV et « exécution immédiate » sont identiques à ceux de la page déléguée.
3. Au clic sur « Confirmer », les appels suivants s'enchaînent :
   - preuve d'acceptation (`/api/booking/accept-terms`, inchangé) ;
   - `POST /api/customer/booking/preflight` ;
   - `POST /api/customer/booking/create`, avec une clé d'idempotence unique par intention.
4. La page `/compte/reservation?cle=…` affiche la confirmation. Si la réservation est en attente de vérification ou de rapprochement, elle interroge `/api/customer/booking/status` toutes les 5 secondes.

Cas d'erreur :

- **Créneau perdu** : proposition de choisir un autre créneau.
- **Véhicule incomplet** : sélecteur de modèle Mercure.
- **Session expirée** : invitation à se reconnecter.
- **Serveur non qualifié** : bascule vers le chemin délégué MercureWeb, avec le même formulaire que la page actuelle. Elle n'est jamais soumise automatiquement : le client clique.
- **Issue incertaine** (réseau, 5xx) : le statut est vérifié avant toute bascule. Une clé inconnue entraîne la bascule. Une clé connue affiche « en attente ». Cela évite les doublons.

Si l'interrupteur est actif mais qu'un prérequis manque, `/go/booking` revient **automatiquement** à la page déléguée identique. Les prérequis sont : disponibilité fermée, écriture désactivée, validation absente ou expirée, session admin Mercure invalide, prestation ou créneau non pris en charge, erreur de rendu.

## Décisions en attente : où chacune se règle

| Décision | Réglage | Défaut |
| --- | --- | --- |
| Activation du parcours | `CHECKUPAUTO_IN_SITE_BOOKING_ENABLED=true` | absent : chemin délégué |
| Canal d'écriture | `CHECKUPAUTO_MERCURE_CUSTOMER_WRITE_ENABLED=true`. Seul l'adaptateur Mercure VL existe aujourd'hui. Le choix d'AutoBilan demanderait un nouvel adaptateur derrière la même interface. | désactivé |
| Identifiants ligne et opérateur | `CHECKUPAUTO_MERCURE_VL_LINE_ID`, `CHECKUPAUTO_MERCURE_VL_OPERATOR_ID`, repris dans `provider` de la preuve signée | vides |
| Validation et preuve de mise en production | `CHECKUPAUTO_BOOKING_SIGNOFF_FILE` et `CHECKUPAUTO_BOOKING_SIGNOFF_KEY_FILE` (voir doc 1) | aucune preuve, donc fermé |
| Qui envoie les confirmations | `CHECKUPAUTO_MERCURE_NOTIFY_EMAIL_CONFIRMATION`, `…_PRINT_CONFIRMATION`, `…_SMS_CONFIRMATION`, `…_SMS_REMINDER` (`true` ou `false`) | absents : charge utile inchangée |
| Modèle générique « Autres modèles » | `CHECKUPAUTO_MERCURE_ALLOW_GENERIC_MODEL=true` | masqué |
| Paiement | Hors périmètre. La politique de paiement Mercure (`mercure_vl_payment_policy_source`) reste le seul arbitre, et aucun module de paiement n'est modifié. Les capacités de paiement ne sont jamais déclarées. | inchangé |
| Session admin Mercure de production | Surveillée par `/api/admin/mercure/booking-health`. Une session invalide entraîne la bascule vers le chemin délégué. | — |
| Réservation de test réelle | Aucune n'est effectuée par ce code ni par ses tests. | — |

## Activation (ordre conseillé)

1. Renseigner la ligne, l'opérateur et l'écriture : `CHECKUPAUTO_MERCURE_CUSTOMER_WRITE_ENABLED`, `CHECKUPAUTO_MERCURE_VL_LINE_ID` et `CHECKUPAUTO_MERCURE_VL_OPERATOR_ID`.
2. Produire et signer la preuve de validation (étapes 5 et 6, preuve d'activation), comme décrit dans la doc 1.
3. Choisir les notifications (doc 2).
4. Vérifier `/api/admin/mercure/booking-health?refresh=1` : `readiness.bookingEnabled` et `session.connected` doivent valoir `true`.
5. Passer `CHECKUPAUTO_IN_SITE_BOOKING_ENABLED=true`.

**Retour arrière** : retirer `CHECKUPAUTO_IN_SITE_BOOKING_ENABLED`. Le chemin délégué redevient immédiatement identique à l'actuel.

## Points notés sans changement

- L'indicateur `callOnly` de `/api/booking/services` est codé en dur dans `admin_server.py`. Il n'a pas été modifié.
- `docs/in-site-booking-contract.md` considère qu'une redirection MercureWeb n'est pas un repli conforme. Le repli délégué a pourtant été demandé explicitement : il reste manuel (clic du client) et utilise le formulaire actuel.
