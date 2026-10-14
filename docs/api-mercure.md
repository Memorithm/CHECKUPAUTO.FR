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
| `POST /api/customer/booking/mercure-checkout` | Réserve et lance le paiement **Payline de Mercure** ; renvoie l'URL de paiement vers laquelle rediriger le client | client connecté + CSRF | **nouveau**, derrière `CHECKUPAUTO_MERCURE_HOSTED_PAYMENT_ENABLED` |
| `POST /api/customer/booking/mercure-checkout/status` | Au retour du client : confirme la réservation seulement si le planning admin Mercure montre un paiement en ligne | client connecté + CSRF | **nouveau** |
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
| `POST /add_rendezvous_client_libre` (`p_centre=1`) | **écriture** publique + paiement Payline Mercure | `mercure-checkout`, uniquement si l'interrupteur est actif |

## Session admin Mercure renouvelée automatiquement

Quand la session admin expire, les réservations sur le site basculent vers le parcours délégué. Le site peut désormais rouvrir la session seul avec le compte Mercure dédié :

- `CHECKUPAUTO_MERCURE_ADMIN_USERNAME` et `CHECKUPAUTO_MERCURE_ADMIN_PASSWORD`, à définir uniquement dans l'environnement du serveur (jamais dans un fichier du dépôt).
- Le renouvellement n'a lieu que si Mercure répond « session expirée ou absente », pas en cas de panne réseau.
- Une tentative au plus toutes les 5 minutes par processus, pour ne pas bloquer le compte en cas de mot de passe erroné.
- L'identifiant et le mot de passe ne sont jamais renvoyés, journalisés ni écrits ; seuls les cookies de session sont stockés, comme lors d'une connexion manuelle depuis l'admin.
- Sans ces variables, le comportement est inchangé.

## Paiement : Payline de Mercure

Relevé en direct du 14 octobre 2026 (`/mnt/project-files/mercure/analyse-admin.md` dans le projet) : les prestations 1763, 1771 et 1759 sont en **paiement en ligne obligatoire** dans Mercure (`paiementWeb=true`, `paiementCentre=false`). Mercure ne lance son paiement Payline que depuis l'appel public `POST /add_rendezvous_client_libre` avec `p_centre=1` (nommage inversé : 1 = en ligne). La réponse est l'URL vers laquelle le navigateur doit aller, ou `error`.

Parcours `mercure-checkout` :

1. Contrôle du créneau, du prix et du véhicule (même préflight que le parcours sur site), puis vérification que Mercure propose bien le paiement en ligne pour la prestation.
2. La clé d'idempotence est réservée **avant** l'appel : une même clé n'est jamais renvoyée à Mercure, puisque l'appel crée un vrai rendez-vous.
3. L'appel est fait par le serveur. Mercure **crée le rendez-vous et bloque le créneau dès cet appel**, avant tout paiement, et renvoie directement la page Payline de production (`https://webpayment.payline.com/v2/?token=…`). L'URL n'est acceptée que sur `webpayment.payline.com` ou `rdv.checkupauto.fr` ; toute autre réponse est traitée comme incertaine, sans nouvel essai.
4. Le client paie sur la page Payline de Mercure, **ouverte dans un nouvel onglet** (`openInNewTab`). Après paiement, Payline le renvoie sur la page Mercure `/confirmation_rdv/<code>`, pas sur notre site, et nous ne pouvons pas changer cette adresse : seul l'éditeur le pourrait. L'onglet du site reste donc ouvert et interroge `mercure-checkout/status` toutes les 5 secondes (`statusPollSeconds`) jusqu'à la confirmation.
5. À son retour, `mercure-checkout/status` cherche le rendez-vous dans le planning admin (créneau, prestation, e-mail du compte) et ne le confirme que si Mercure y a enregistré une ligne de facturation (par exemple « CARTE BLEUE, 80,00 € »). Le `tokenPayline` est posé dès la création, avant paiement : il ne prouve rien et n'est jamais renvoyé.

Le Payline propre au site (PR #705) reste en place pour le parcours sur site existant ; Mercure ne voit pas ces paiements-là.

**Test réel du 14 octobre 2026** (rendez-vous test payé 80 €, puis remboursé et annulé) : création avant paiement, page Payline de production, paiement visible comme ligne de facturation. Le remboursement (`/admin/rendez_vous_remboursement`) **n'annule pas** le rendez-vous : il reste au planning sans montant ni token, et il faut ensuite l'annuler (`/admin/rendez_vous_remove`) pour libérer le créneau.

**Test d'annulation du 14 octobre 2026** : quand le client clique « Annuler » sur Payline (ou abandonne le lien), il est renvoyé sur `rdv.checkupauto.fr/erreur` puis sur l'accueil Mercure, et **Mercure supprime lui-même le rendez-vous impayé en moins d'une minute**. Le créneau redevient libre sans action du site. Si le client ferme simplement l'onglet Payline, Mercure garde le créneau **environ 15 minutes** avant la même suppression : pendant ce délai le statut reste `payment_pending` et le créneau indisponible. L'onglet du site interroge donc le statut jusqu'à 20 minutes (`statusPollMaxSeconds`). `mercure-checkout/status` répond `payment_cancelled` quand le rendez-vous a disparu du planning ; le client peut recommencer avec une nouvelle clé.

**Encore à confirmer** :

- les formats attendus par l'appel public : `date_rdv` / `heure_rdv` (envoyés en `AAAA-MM-JJ` et `HH:MM`), `energie` (envoyée en identifiant Mercure), `civilite` (vide), `iframe` / `id`.

Tant que ces points ne sont pas confirmés, `CHECKUPAUTO_MERCURE_HOSTED_PAYMENT_ENABLED` doit rester absent.

## À faire

- Lever les points à confirmer ci-dessus, puis brancher le bouton « Payer » de `/go/booking` sur `mercure-checkout` (ouverture de Payline dans un nouvel onglet, attente avec interrogation du statut).
- Option : demander à AutoBilan-Systems un lien de retour vers le site sur `/confirmation_rdv`, ou que cette page appelle `/api/integrations/mercure/browser-confirmed` (déjà prévu côté site pour l'origine rdv.checkupauto.fr).
- Annulation et report côté client : Mercure les permet depuis l'admin (`rendez_vous_remove*`, `rendez_vous_drag_and_drop`) et rembourse via `rendez_vous_remboursement` (token Payline + montant). Une annulation payée doit enchaîner remboursement puis suppression. Il reste à fixer la règle de remboursement.
