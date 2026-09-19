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

## Cycle de vie et erreurs APNs

Les réponses APNs sont classées avant toute nouvelle tentative. `410 Unregistered` et `400 BadDeviceToken` rendent le jeton courant inutilisable : le registre compare le hash du jeton avec la valeur encore attachée à l’installation, efface le jeton brut et purge ses échéances serveur. Cette comparaison évite qu’une réponse tardive invalide un nouveau jeton enregistré entre-temps. L’application pourra ensuite réenregistrer un nouveau jeton avec la même identité d’installation.

Les erreurs de configuration fournisseur (`DeviceTokenNotForTopic`, topic/certificat/provider token invalides) n’invalident pas les appareils. Le batch s’arrête après la première de ces erreurs afin de ne pas répéter le même défaut pour tous les destinataires. Les erreurs transitoires (`429`, `500`, `503` et erreurs réseau HTTP/2) restent éligibles à une exécution ultérieure. La console n’expose que des compteurs agrégés de jetons retirés et jamais les jetons eux-mêmes.
## Action Réserver

Les rappels de contrôle technique utilisent la catégorie iOS stable CHECKUPAUTO_CT_DUE. Cette catégorie expose l’action CHECKUPAUTO_BOOK, affichée comme **Réserver**. La même catégorie est utilisée par APNs et par le fallback local afin que le comportement utilisateur ne dépende pas du canal. Lorsque l’utilisateur choisit cette action, l’application recharge le bootstrap mobile et ouvre l’URL de réservation fournie par le serveur ; l’URL commerciale n’est donc pas dupliquée dans le routage de notification.

## Cycle de vie côté iPhone

Le fait que le push distant soit activé côté serveur ne suffit pas à désactiver le fallback local sur un iPhone. Le fallback reste actif jusqu’à ce que cet appareil ait effectivement reçu un jeton APNs et que son enregistrement auprès de CheckupAuto ait répondu avec succès. Cette confirmation est conservée localement par installation.

Si l’autorisation de notifications est retirée dans Réglages, l’application réévalue l’état au retour au premier plan, marque le push distant de cet appareil comme inactif et appelle l’API de désinscription. Le serveur efface alors le jeton APNs actif et les échéances mobiles liées à cette installation. Un échec d’enregistrement APNs suit la même stratégie de sûreté : l’application revient au fallback local et tente de retirer tout ancien jeton serveur.

Lorsque l’autorisation est de nouveau accordée, l’application demande un nouveau jeton APNs. Le fallback local n’est supprimé qu’après confirmation du nouvel enregistrement serveur, ce qui évite une fenêtre sans rappel lors d’un renouvellement de jeton ou d’une panne réseau.
