# Audit : points restants (octobre 2026)

Ce document suit la PR des derniers constats de l'audit. Il complète `docs/audit-faible-info.md`.

## Corrigé dans le code

- **Q-03** : `sqlite_closing.ClosingConnection` ferme la connexion à la sortie du bloc `with`, après le commit ou le rollback. Tous les magasins applicatifs l'utilisent via `factory=ClosingConnection` : comptes, conformité, appareils, notifications, rappels, veille concurrentielle, rapports CT, avis, journal de réservation, OIDC et analytics. Le test `sqlite_closing_test.py` couvre ce comportement. Les curseurs sont tous consommés dans le bloc ; `rowcount` reste lisible après la fermeture.
- **D-01** : `requirements.lock` est généré par `uv pip compile --generate-hashes --universal` (Python ≥ 3.10) depuis `requirements.txt`, qui reste la source éditée à la main.
  - L'image Docker, la release Hostinger (`deployment_release.py`, si le verrou est livré) et Security CI l'installent avec `--require-hashes`.
  - Vérifié localement : installation en Python 3.10 et 3.12 (x86_64), téléchargement des roues aarch64 (runner et hôte ARM64).
  - `requirements_lock_test.py` vérifie que chaque version épinglée dans `requirements.txt` est identique dans le verrou et que chaque paquet porte ses empreintes.
- **F-02** : les données structurées ajoutent `geo` (GeoCoordinates) et `hasMap`. Les coordonnées sont celles déjà publiées par le lien d'itinéraire de `index.html` (48.980120, 1.890251). Les horaires (`openingHoursSpecification`) et les profils sociaux (`sameAs`) ne figurent nulle part dans le dépôt : ils ne sont pas inventés.

## S-07 : séparation des clés d'index et de chiffrement (plan, non appliqué)

`customer_accounts` utilise la même clé maîtresse pour deux usages :

- les index HMAC (`_hmac(label, valeur)`, séparés par libellé) ;
- le chiffrement AES-GCM des profils (AAD = identifiant de compte).

Le CSRF a déjà sa sous-clé HKDF (#689).

Séparer les deux autres usages réécrit toutes les lignes existantes. Faute de pouvoir tester cette migration sur une copie des données de production, elle n'est pas faite ici. Migration sûre proposée :

1. Ajouter `_subkey("index")` et `_subkey("profile")`, ainsi qu'une colonne `key_version`, à 1 pour les lignes existantes.
2. En lecture, essayer la version de la ligne. En écriture, toujours utiliser la version 2.
3. Pour les index, calculer l'ancien et le nouveau HMAC lors des recherches tant que la migration n'est pas finie.
4. Migrer par lots dans une transaction `BEGIN IMMEDIATE`, après une sauvegarde chiffrée vérifiée (la restauration doit avoir été testée).
5. Une fois toutes les lignes en version 2, retirer la double lecture.

Le CSRF de `payment_contract_http` (mot de passe admin) reste hors périmètre (paiements).

## Q-05 : inventaire du code potentiellement mort (aucune suppression)

Ces modules racine ne sont importés par aucun module de production, script, workflow ou fichier de déploiement. Seuls leurs tests les référencent. Ce sont des candidats à archiver, après confirmation par l'équipe : certains servent de preuves d'homologation Mercure.

- **Contrats et preuves Mercure, une étape par fichier (7 à 39 lignes)** :
  - `mercure_step1_provider_metadata` … `mercure_step6_production_signoff` ;
  - les fichiers `mercure_vl_*` (12 modules) ;
  - `mercure_legacy_gateway_contract`, `mercure_model_selection_guard`, `mercure_booking_js_parameter_contract`.
- **Outils lancés à la main (ont un `__main__`)** : `mercure_booking_homologation_probe`, `mercure_booking_live_rehearsal`, `marketing_campaign_cli`, `local_runtime_permissions`, `app_qr_assets`.
- **Compositions et rapports de réservation** : `customer_booking_http_composition`, `customer_booking_http_trusted_composition`, `customer_booking_acceptance_report`, `customer_booking_activation_evidence`.
- **Support de tests** : `admin_http_test_support`.
- `payment_contract_cli` et `payment_monetico` apparaissent aussi dans la liste, mais restent hors périmètre (paiements).

Le dépôt compte environ 220 modules et 460 fichiers de tests à la racine. Un découpage en paquets (`checkupauto/accounts`, `checkupauto/mercure`, `checkupauto/mobile`…) doit être fait module par module, avec des réexports de compatibilité, dans des PR dédiées.

## Décisions réservées à Tarek

- CSP : retrait de `'unsafe-inline'` (styles et scripts en ligne à externaliser), `img-src` et `report-to`.
- HSTS `preload` (engagement difficile à annuler pour tout le domaine).
- Durées de conservation légales (comptes inactifs, preuves, journaux).
- Coût des minutes macOS hébergées par GitHub, ou retour à un Mac auto-hébergé (`CHECKUPAUTO_IOS_SELF_HOSTED=true`).
- Libellés de confidentialité dans App Store Connect, à aligner sur `PrivacyInfo.xcprivacy` (PR iOS).
