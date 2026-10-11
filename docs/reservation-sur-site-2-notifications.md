# Réservation sur le site : 2. Notifications Mercure (décision 3)

Qui envoie la confirmation et les rappels au client ? La décision n'est pas encore prise. Le code ne présume rien : chaque champ de notification du formulaire Mercure `rendez_vous_add` correspond à un interrupteur explicite.

| Variable d'environnement | Champ Mercure | Valeurs |
|---|---|---|
| `CHECKUPAUTO_MERCURE_NOTIFY_EMAIL_CONFIRMATION` | `email_confirmation_vl` | `true`, `false` ou absent |
| `CHECKUPAUTO_MERCURE_NOTIFY_PRINT_CONFIRMATION` | `imprime_confirmation_vl` | `true`, `false` ou absent |
| `CHECKUPAUTO_MERCURE_NOTIFY_SMS_CONFIRMATION` | `envoi_sms_vl` | `true`, `false` ou absent |
| `CHECKUPAUTO_MERCURE_NOTIFY_SMS_REMINDER` | `rappel_sms_vl` | `true`, `false` ou absent |

- **Absent (valeur par défaut)** : le champ n'est pas envoyé, donc le formulaire est identique à l'existant. Mercure applique alors son comportement par défaut, **qui n'a pas encore été observé**.
- Seules les chaînes exactes `true` et `false` sont acceptées. Toute autre valeur (`1`, `oui`, `TRUE`…) est une erreur de configuration : l'écriture est refusée **avant** l'ouverture de la session Mercure.

## Configurations types, selon la décision

- **Mercure envoie confirmation et rappels** : `…EMAIL_CONFIRMATION=true`, `…SMS_CONFIRMATION=true` et `…SMS_REMINDER=true`.
- **CheckupAuto envoie seul** : les quatre variables à `false`. La notification CheckupAuto reste à brancher ; aucun envoi n'est activé par ce changement.
- **Mixte**, par exemple e-mail par CheckupAuto et rappel SMS par Mercure : `…EMAIL_CONFIRMATION=false` et `…SMS_REMINDER=true`.

À valider lors de l'essai contrôlé (décision 7) : relire dans Mercure qu'un rendez-vous créé avec ces champs n'a déclenché que les notifications attendues. Ce point correspond à la case `notifications` de step6.
