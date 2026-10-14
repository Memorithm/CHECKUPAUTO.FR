# API Mercure du site : carte complète

Ce document décrit l'API qui relie checkupauto.fr (dont test.checkupauto.fr) au planning Mercure de rdv.checkupauto.fr (éditeur AutoBilan-Systems, centre 240). Mercure n'expose pas d'API partenaire : le site s'appuie sur les mêmes appels que les pages publiques Mercure et sur l'admin Mercure avec un compte dédié.

## Routes exposées par le site

| Route | Rôle | Accès | État |
| --- | --- | --- | --- |
| `GET /api/booking/services` | Prestations réservables (1763 contrôle technique, 1771 véhicule aménagé) | public | actif |
| `GET /api/booking/availability?service=&date=` | Créneaux et prix lus en direct dans Mercure (cache 20 s, coupe-circuit) | public | actif |
| `GET /api/booking/payment-options?service=` | Modes de paiement que Mercure propose pour la prestation : `online` (paiement web Mercure, Payline) et `centre` (cache 5 min) | public | **nouveau** |
| `POST /api/customer/booking/preflight` | Contrôle complet avant écriture (créneau relu, véhicule, prix) | client connecté | derrière interrupteur |
| `POST /api/customer/booking/create` | Écriture du rendez-vous dans Mercure, idempotente | client connecté + CSRF | derrière interrupteur |
| `GET /api/customer/booking/status?cle=` | État de la demande (préparée, à rapprocher, confirmée) | client connecté | actif |
| `POST /api/customer/booking/payment/start` | Démarre le paiement Payline d'un rendez-vous confirmé | client connecté + CSRF | derrière interrupteur |
| `GET /api/customer/booking/payment-status?cle=` | État du paiement relu côté serveur | client connecté | actif |
| `GET /api/customer/booking/readiness` | Prérequis du parcours sur site | client connecté | actif |
| `GET /api/admin/mercure/session-status` | Validité de la session admin Mercure (renouvelée automatiquement, voir plus bas) | admin | actif |
| `GET /api/admin/mercure/booking-health` | Santé du parcours : session, échecs d'écriture, alertes | admin | actif |

Le parcours de bout en bout et ses interrupteurs sont décrits dans `reservation-sur-site.md`.

## Appels Mercure utilisés

| Appel Mercure | Type | Utilisé par |
| --- | --- | --- |
| `POST /prendre_rdv` (id=240) | lecture publique, ouvre la session | disponibilités, options de paiement |
| `POST /rech_dispon_rdv` | lecture publique | disponibilités |
| `POST /get_energie_prestation` | lecture publique | options de paiement (`paiementWeb`, `paiementCentre`) |
| `POST /admin/login` | connexion admin | renouvellement de session |
| `GET /admin/calendrier`, `GET /admin/rendez-vous/json`, `POST /admin/rdv_by_client` | lecture admin | santé, relecture après écriture, rapprochement |
| `POST /admin/rendez_vous_add` | **écriture** | création de rendez-vous (désactivée par défaut) |
| `POST /admin/rendez_vous_remove` | **suppression** | rendez-vous de test synthétiques uniquement |
| `POST /add_rendezvous_client_libre` | **écriture** publique | jamais appelé par le site |

## Session admin Mercure renouvelée automatiquement

Quand la session admin expire, les réservations sur le site basculent vers le parcours délégué. Le site peut désormais rouvrir la session seul avec le compte Mercure dédié :

- `CHECKUPAUTO_MERCURE_ADMIN_USERNAME` et `CHECKUPAUTO_MERCURE_ADMIN_PASSWORD`, à définir uniquement dans l'environnement du serveur (jamais dans un fichier du dépôt).
- Le renouvellement n'a lieu que si Mercure répond « session expirée ou absente », pas en cas de panne réseau.
- Une tentative au plus toutes les 5 minutes par processus, pour ne pas bloquer le compte en cas de mot de passe erroné.
- L'identifiant et le mot de passe ne sont jamais renvoyés, journalisés ni écrits ; seuls les cookies de session sont stockés, comme lors d'une connexion manuelle depuis l'admin.
- Sans ces variables, le comportement est inchangé.

## Paiement : Payline du site ou Payline de Mercure

Deux chemins existent :

1. **Payline du site** (en place, PR #705) : le site écrit le rendez-vous dans Mercure, puis encaisse via sa propre intégration Payline / Monext. Mercure ne voit pas ce paiement.
2. **Payline de Mercure** : le paiement en ligne configuré dans Mercure (`paiementWeb`). Le 9 octobre 2026, Mercure répondait `paiementWeb=false` pour la prestation 1763. `GET /api/booking/payment-options` indique en direct si ce paiement est désormais actif.

Le raccordement du chemin 2 dans le site demande d'observer, en lecture seule, ce que fait la page publique Mercure après le choix du créneau quand `paiementWeb` est vrai (appel de création, redirection Payline, retour). Cette observation n'a pas encore pu être faite : l'environnement de développement n'a pas accès à rdv.checkupauto.fr.

## À faire

- Relever le parcours de paiement web de Mercure (lecture seule) et décider du chemin de paiement.
- Gestion des rendez-vous côté client (liste, annulation, report) : non exposée. La suppression Mercure existe (`/admin/rendez_vous_remove`) mais l'annulation d'un rendez-vous payé implique un remboursement Payline et une règle métier à fixer.
