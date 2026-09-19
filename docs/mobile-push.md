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

Le topic par défaut est `fr.checkupauto.reminder`. L'environnement APNs est attaché à chaque appareil (`sandbox` pour une build Debug, `production` pour une build Release) ; le serveur choisit donc le bon endpoint Apple au moment de chaque envoi. Le transport utilise l'API HTTP/2 APNs avec un provider token ES256 à durée courte.

## Synchronisation des échéances mobiles

`POST /api/mobile/reminders/sync` exige la même identité d'installation authentifiée. L'application transmet un instantané borné à 24 échéances, chacune réduite à un UUID opaque `deadlineId` et une date ISO `dueDate`. Elle ne transmet ni immatriculation, ni libellé véhicule, ni identifiant client, ni donnée Mercure. La suppression d'un véhicule dans l'application supprime l'échéance correspondante du registre serveur au prochain instantané. La désinscription d'un appareil purge également ses échéances.

Le moteur `mobile_reminder_dispatch.py` applique la même politique centrale que l'application (J-60/J-30/J-15/J-7/J-1 à 09:00 Europe/Paris) et passe par `NotificationBroker` pour l'idempotence. L'envoi distant est volontairement désactivé tant que `CYBERCHECK_MOBILE_PUSH_ENABLED` n'est pas explicitement activé et que les identifiants APNs privés ne sont pas présents. `/api/mobile/bootstrap` expose alors `notifications.remotePushActive`; l'application supprime ses notifications locales lorsque le push central est actif, sinon elle conserve les notifications locales comme repli sûr.
