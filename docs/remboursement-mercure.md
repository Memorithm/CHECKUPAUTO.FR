# Remboursement d'une réservation payée sur Mercure

Menu **Remboursements Mercure** du back-office (`/admin/refunds.html`). Il rembourse une réservation payée en ligne avec le Payline de Mercure (parcours de `mercure_hosted_checkout`). Le remboursement est exécuté par Mercure (`/admin/rendez_vous_remboursement`), sur la carte du client. Il ne concerne pas le Payline propre au site, dont les remboursements restent absents du back-office.

## Activation

- `CHECKUPAUTO_MERCURE_REFUND_ENABLED=true` : désactivé par défaut.
- `CHECKUPAUTO_MERCURE_REFUND_DAILY_CAP_EUR` : plafond quotidien du total remboursé, 300 € par défaut.
- La double authentification du back-office doit être configurée. Sans elle, toutes les routes répondent `two_factor_not_configured`.
- Une session Mercure doit être ouverte (Mercure RDV → Session Mercure).

## Déroulé

1. **Recherche** (`POST /api/admin/mercure-refunds/lookup`), en lecture seule : numéro du rendez-vous et date. Le serveur lit le planning Mercure et renvoie un récapitulatif. Le nom et l'e-mail du client sont masqués, et le token Payline n'est jamais renvoyé. Si le rendez-vous est payé en ligne et jamais remboursé, le serveur délivre une confirmation signée (HMAC). Elle est liée au rendez-vous, au montant, à l'option d'annulation et à la session de l'admin (Basic + cookie 2FA), et expire après 5 minutes.
2. **Exécution** (`POST /api/admin/mercure-refunds/execute`). Il faut la confirmation, le numéro et le montant retapés, et un **nouveau code Google Authenticator** : un code à usage unique (déjà utilisé = refusé), jamais un code de récupération. Sous verrou, le serveur vérifie ensuite :
   - que la confirmation n'a pas déjà servi ;
   - qu'aucun remboursement n'est déjà enregistré pour ce rendez-vous ;
   - que le plafond du jour n'est pas dépassé ;
   - en relisant le planning, que le rendez-vous est toujours payé et que le montant ne dépasse pas `tarifTotal`.

   Il écrit l'entrée du journal (`pending`) **avant** d'appeler Mercure, puis appelle Mercure, puis annule le rendez-vous si l'option est cochée.
3. **Résultat incertain** (coupure réseau pendant l'appel) : l'état `uncertain` bloque tout nouvel essai. `POST /api/admin/mercure-refunds/verify` relit le planning. Un token et une facturation vidés indiquent `refunded`. S'ils sont toujours présents, l'état passe à `refused` et un nouvel essai est possible. Un rendez-vous disparu reste `uncertain` : vérifiez-le dans Mercure et Payline.

Toutes les routes exigent la connexion admin et une session 2FA valide, et refusent une URL avec paramètres. Les POST exigent en plus la même origine, du JSON de 4 Ko au plus et un jeton CSRF `X-CheckupAuto-Refund-CSRF`. Un code 2FA faux compte comme un échec d'authentification pour Sentinel.

## Stockage

`$CYBERCHECK_PRIVATE_DIR/mercure-refunds/` (dossier 0700, fichiers 0600) :
- `journal.json` : état par rendez-vous ;
- `audit.jsonl` : journal en ajout seul ;
- `used-confirmations.json` : confirmations déjà utilisées ;
- `confirmation.key` : clé HMAC.

Seuls le numéro de rendez-vous, le montant, l'état et l'heure y figurent. Aucune donnée client, carte ou token Payline n'y est écrite.

## Rappels Mercure (essais du 14 et 15/10/2026)

- Le remboursement n'annule pas le rendez-vous. Mercure vide le token, `tarifTotal` et la facturation, puis le rendez-vous est supprimé avec `rendez_vous_remove`.
- « Supprimer le rendez-vous » dans l'admin Mercure ne rembourse pas.
- Après un remboursement, le token est vidé : un second remboursement partiel du même rendez-vous est impossible.
