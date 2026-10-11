# Réservation sur le site : 3. Correspondance du véhicule avec Mercure

Pour écrire un rendez-vous, Mercure a besoin des identifiants de marque, modèle et énergie. Ces identifiants sont résolus par `mercure_vehicle_reference_resolver`, avec une correspondance **exacte** des libellés.

Quand la correspondance échoue (véhicule saisi ailleurs, libellé Mercure modifié…), le parcours sur le site propose un **sélecteur de repli**.

## API (client connecté)

- `GET /api/customer/booking/vehicle-mapping?vehicleId=…` : indique si la correspondance est vérifiée (`verified`, `reason`, `current`, `genericModelAllowed`). Cette route ne fait que lire les listes de référence Mercure.
- `POST /api/customer/booking/vehicle-mapping` : corps `{"vehicleId","brandId","modelId","energyId"}`, avec contrôle de même origine et en-tête `X-CheckupAuto-Customer-CSRF`.
  - Les identifiants sont **revérifiés** dans les listes Mercure en direct, et le modèle doit appartenir à la marque choisie.
  - Seuls la marque, le modèle et l'énergie du véhicule du client sont remplacés par les libellés Mercure exacts (`customer_accounts.update_vehicle_characteristics`). L'immatriculation et le numéro de formule ne sont pas modifiés.
  - **Aucune écriture dans Mercure.**

## « Autres modèles » (option, désactivée par défaut)

| Variable | Effet |
|---|---|
| `CHECKUPAUTO_MERCURE_ALLOW_GENERIC_MODEL=true` | Autorise la ligne générique Mercure « Autres modèles » dans le sélecteur et dans la résolution. |
| absente (par défaut) ou toute autre valeur | Refus (`vehicle_reference_generic_model_unqualified`), comme aujourd'hui. |

Cette option reste désactivée tant qu'on ne sait pas si Mercure et le centre acceptent une fiche « Autres modèles » pour un rendez-vous réel. À vérifier lors de l'essai contrôlé (décision 7).
