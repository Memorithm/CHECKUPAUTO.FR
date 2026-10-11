# Réservation sur le site : 4. Observabilité

Module `booking_health`.

## Signaux

- **Session admin Mercure** : `session_status()` appelle `mercure_admin_client.session_status()`, une lecture de `/admin/calendrier` sans aucune écriture.
  - Le résultat est mis en cache 60 s.
  - Les exceptions sont converties en état (`session_unavailable`, `timeout`, `unexpected_error`…), jamais propagées.
- **Créations** (`POST /api/customer/booking/create`), réparties en compteurs en mémoire :
  - `confirmed` ;
  - `reconciliationRequired` (résultat incertain : vérifier dans Mercure, aucun rejeu) ;
  - `providerFailures` (contexte fournisseur, écriture, exception) ;
  - `slotLost` (créneau pris entre-temps) ;
  - `customerErrors` (requête invalide) ;
  - `disabled` (fonction non activée : situation attendue par défaut).

## Consultation (administrateur)

`GET /api/admin/mercure/booking-health` : authentification Basic plus double authentification si elle est configurée. Ajouter `?refresh=1` pour forcer la vérification de la session.

Réponse : état de disponibilité (`readiness`), compteurs, dernier échec fournisseur, dernière réconciliation, état de la session.

## Alertes

Les alertes passent par `security_alerts.emit`. Elles sont enregistrées localement et livrées au webhook `CYBERCHECK_SECURITY_ALERT_WEBHOOK` **s'il est déjà configuré**.

Elles ne sont émises **que si `CHECKUPAUTO_IN_SITE_BOOKING_ENABLED=true`**. Avec la configuration par défaut, aucune alerte n'est émise et aucun nouvel envoi externe n'existe.

| Type | Niveau | Déclencheur |
|---|---|---|
| `booking_mercure_session` | high | session admin invalide ou expirée |
| `booking_mercure_write` | high | échec fournisseur à la création |
| `booking_mercure_reconciliation` | high | création au résultat incertain |

- Anti-doublon : une même alerte n'est pas réémise pendant 30 min.
- Les alertes ne contiennent aucune donnée client.

**Action attendue sur `booking_mercure_session`** : renouveler la session, par exemple avec le workflow RemoteOps `hostinger-mercure-session-sync` (décision 6 pour la production).
