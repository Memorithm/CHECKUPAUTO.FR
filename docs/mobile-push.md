# Notifications iOS et APNs

L'application iOS conserve une identité d'installation locale distincte des données Mercure. Lors de l'autorisation des notifications, iOS fournit un jeton APNs ; l'application génère un `installationId` aléatoire et un secret d'enregistrement de 256 bits, conservés dans le Trousseau Apple (`ThisDeviceOnly`). Le serveur ne renvoie jamais le jeton APNs ni le secret dans ses API d'administration.

## API d'enregistrement

`POST /api/mobile/devices/register` accepte uniquement du JSON avec `installationId`, `registrationSecret`, `deviceToken` et `environment` (`sandbox` ou `production`). Les mises à jour d'une installation existante exigent le même secret. `POST /api/mobile/devices/unregister` désactive l'installation et efface le jeton brut du registre privé.

Le registre est stocké dans `CYBERCHECK_DATA_DIR/mobile-devices.sqlite3`, en dehors du dépôt Git. La console expose uniquement des compteurs agrégés via `/api/admin/mobile/devices/status`.

## Identifiants APNs privés

Les identifiants Apple ne doivent jamais être ajoutés au dépôt. Le serveur attend par défaut :

- `/root/CyberCheckPrivate/apns-key.p8`
- `/root/CyberCheckPrivate/apns-key-id`
- `/root/CyberCheckPrivate/apns-team-id`

Le topic par défaut est `fr.checkupauto.reminder`. `CYBERCHECK_APNS_ENVIRONMENT` choisit `sandbox` ou `production`. Le transport utilise l'API HTTP/2 APNs avec un provider token ES256 à durée courte.

L'enregistrement sécurisé des appareils et le transport sont indépendants des données Mercure. Une association explicite entre une échéance mobile et une installation devra être ajoutée avant d'utiliser les push pour les relances d'échéance ; le système ne diffuse donc aucun push automatique à ce stade.
