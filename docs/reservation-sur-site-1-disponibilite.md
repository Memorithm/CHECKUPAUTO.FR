# Réservation sur le site — 1. Disponibilité pilotée par la configuration

Statut : code livré, **désactivé par défaut**. Avec la configuration par défaut, le parcours reste strictement le parcours délégué actuel : `/go/booking` redirige vers `rdv.checkupauto.fr`.

Ce document décrit chaque interrupteur, et la décision de Tarek à laquelle il correspond. Aucune valeur n'est présumée dans le code.

## 1. Disponibilité de la réservation sur le site (`in_site_booking_readiness`)

`declared_capabilities()` renvoie des capacités toutes à `False`, **sauf si les trois conditions suivantes sont réunies** :

| Condition | Configuration | Valeur par défaut |
|---|---|---|
| Interrupteur du parcours sur le site | `CHECKUPAUTO_IN_SITE_BOOKING_ENABLED=true` (exactement `true`) | absent : fermé |
| Écriture fournisseur autorisée | `CHECKUPAUTO_MERCURE_CUSTOMER_WRITE_ENABLED=true`, plus `CHECKUPAUTO_MERCURE_VL_LINE_ID` et `CHECKUPAUTO_MERCURE_VL_OPERATOR_ID` (numériques) | absent : fermé |
| Validation de production signée | document `booking-signoff.json` authentique, non expiré, lié à la ligne et à l'opérateur configurés | absent : fermé |

Les capacités de paiement (`payment_required`, `embedded_payment_qualified`, `payment_result_verified`) ne sont jamais déclarées. La règle de paiement appliquée à chaque requête (`customer_booking_payment_policy`) refuse toujours un paiement en ligne non vérifié. En pratique, seul le **paiement au centre** peut aboutir.

### Document de validation (`booking_signoff_evidence`)

- Emplacement : `CHECKUPAUTO_BOOKING_SIGNOFF_FILE`. Par défaut : `$CYBERCHECK_PRIVATE_DIR/booking-signoff.json`.
- Clé HMAC : `CHECKUPAUTO_BOOKING_SIGNOFF_KEY_FILE`. Par défaut : `$CYBERCHECK_PRIVATE_DIR/booking-signoff.key`. La clé fait 32 octets au minimum, avec des permissions `600` ou `400`. Une clé lisible par le groupe ou les autres est refusée.
- Schéma `checkupauto.booking-signoff/v1`. Les champs ci-dessous sont exacts : tout champ en plus ou en moins entraîne un refus.

```json
{
  "schema": "checkupauto.booking-signoff/v1",
  "issuedAt": "2026-11-02T09:00:00+01:00",
  "expiresAt": "2026-12-02T09:00:00+01:00",
  "approvedBy": "Tarek Zekriti",
  "provider": {"lineId": "<ligne>", "operatorId": "<opérateur>"},
  "step5": {"authenticated": true, "billing_complete": true, "vehicle_qualified": true,
            "slot_verified": true, "provider_receipt": true,
            "independent_identity": true, "confirmation_displayed": true},
  "step6": {"security_ci": true, "customer_e2e": true, "provider_identity": true,
            "duplicate_recovery": true, "monitoring": true, "rollback": true,
            "notifications": true, "payment_policy_verified": true},
  "activation": {"authenticated_customer": true, "validated_vehicle": true,
                 "authoritative_slot": true, "provider_line_verified": true,
                 "provider_service_verified": true, "provider_duration_verified": true,
                 "writer_qualified": true, "independent_identity_reader": true,
                 "idempotency_qualified": true, "payment_policy_verified": true,
                 "rollback_verified": true, "monitoring_verified": true},
  "signature": "<hex HMAC-SHA256>"
}
```

- La signature couvre le JSON canonique de tous les champs sauf `signature` : clés triées, séparateurs `,` et `:`, UTF-8. Voir `booking_signoff_evidence.canonical_bytes`.
- La validité est de 90 jours au maximum.
- Chaque liste est contrôlée par son module d'origine : `mercure_step5_customer_journey`, `mercure_step6_production_signoff` et `customer_booking_activation_evidence`. Toutes les valeurs doivent être booléennes.
- **Le code ne crée ni ne signe jamais ce document.** La signature est faite par un opérateur, hors du processus web, après les essais contrôlés approuvés par Tarek :

```python
import json, booking_signoff_evidence as s
doc = json.load(open("brouillon.json"))            # sans "signature"
key = open("/chemin/privé/booking-signoff.key", "rb").read().strip()
doc["signature"] = s.compute_signature(doc, key)
json.dump(doc, open("booking-signoff.json", "w"), ensure_ascii=False)
```

### Retour arrière

- Supprimer `CHECKUPAUTO_IN_SITE_BOOKING_ENABLED`, ou le passer à une autre valeur que `true`.
- Ou retirer le document de validation.
- Ou attendre son expiration.

Dans tous ces cas, les capacités repassent immédiatement à `False`, sans redéploiement de code.
