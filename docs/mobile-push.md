# Notifications iOS et APNs

L'application iOS conserve une identité d'installation locale distincte des données Mercure. Au premier démarrage, elle génère un installationId aléatoire et un secret de 256 bits conservés dans le Trousseau Apple (ThisDeviceOnly), puis enregistre cette identité auprès de CheckupAuto indépendamment du consentement aux notifications. Le serveur ne renvoie jamais le secret ni un jeton APNs dans ses API d'administration.

## API d'enregistrement

POST /api/mobile/installations/register enregistre l'identité minimale de l'installation sans exiger de jeton APNs. POST /api/mobile/devices/register attache ensuite le canal push avec deviceToken et environment (sandbox ou production) lorsque l'utilisateur autorise les notifications. Toutes les mises à jour d'une installation existante exigent le même secret.

POST /api/mobile/devices/unregister coupe uniquement le canal APNs, efface le jeton brut et purge les échéances de dispatch, mais conserve le binding véhicule afin qu'une réautorisation puisse le réutiliser. POST /api/mobile/installations/delete est l'opération distincte de suppression complète : elle supprime l'installation, ses échéances et ses bindings.

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

## Priorité des sources d'échéance

Le registre mobile distingue désormais deux provenances : device pour le fallback saisi ou conservé sur l'iPhone, et mercure pour une échéance serveur autoritaire. Tant qu'aucune échéance mercure n'est associée à une installation, les échéances device restent utilisables. Dès qu'une échéance autoritaire existe pour cette installation, le moteur APNs ignore toutes les échéances device de cette installation afin d'éviter un double rappel ou une date contradictoire.

La synchronisation publique de l'iPhone ne peut supprimer ou modifier que les lignes device et ne peut pas écraser une ligne mercure. L'injection mercure est une primitive interne non exposée par l'API mobile publique. Le binding vérifié installation iOS ↔ véhicule Mercure est fourni par le mécanisme de claim décrit plus bas. Le canal QR post-contrôle peut désormais peupler ce binding dès que le préfixe d’identifiant d’application Apple est configuré et que l'application signée possède l'Associated Domain prévu.

## Claim sécurisé d'un véhicule

Le serveur peut créer en interne un claim à usage unique pour un véhicule Mercure déjà vérifié. Le jeton est généré avec 256 bits d'aléa, expire par défaut après 30 minutes et n'est jamais enregistré en clair : seul son SHA-256 est conservé jusqu'à consommation ou expiration.

L'application consomme ce jeton via POST /api/mobile/claims/consume en présentant également son installationId et son registrationSecret. Après authentification, le serveur crée un bindingId UUID opaque. La réponse mobile ne contient ni vehicleId Mercure, ni clientId, ni clientKind. Le claim est supprimé dès sa consommation, ce qui interdit toute réutilisation.

L'émission cryptographique reste interne : aucun endpoint public ne permet d'appeler issue_vehicle_claim. La console d'administration possède un endpoint authentifié qui résout le véhicule dans l'inventaire ReminderEngine issu de Mercure, puis appelle l'émetteur interne. Le QR SVG est produit localement sur CheckupAuto, sans service QR tiers. Le jeton brut n'est jamais persisté et reste uniquement dans le fragment #token=... du lien à usage unique.

Après un claim réussi, CyberCheck tente immédiatement de rapprocher le binding de l'inventaire privé ReminderEngine. Si une échéance Mercure vérifiée est disponible, elle devient la source autoritaire de l'installation ; sinon le fallback device reste en place. Une synchronisation horaire interne maintient ensuite ces échéances à jour.

## Universal Link de claim iOS

L'application contient maintenant un client de consommation du claim. Elle accepte uniquement la forme canonique HTTPS https://www.checkupauto.fr/app/claim avec le jeton placé dans le fragment, par exemple #token=... . Un jeton placé dans la query string, un domaine différent ou HTTP sont refusés. Le fragment n'est pas envoyé au serveur lors de la requête navigateur, ce qui évite de placer le claim dans les journaux HTTP usuels.

Le client réenregistre d'abord l'identité d'installation puis appelle POST /api/mobile/claims/consume. La réponse attend exclusivement un bindingId UUID opaque. Aucun identifiant véhicule ou client Mercure n'est accepté comme résultat mobile.

L'application déclare désormais l'Associated Domain `applinks:www.checkupauto.fr`. Le serveur publie l'Apple App Site Association sur `/.well-known/apple-app-site-association` et `/apple-app-site-association`, limité au chemin `/app/claim`. Le document AASA n'est servi que lorsque le préfixe d’identifiant d’application Apple de dix caractères est disponible ; sinon le serveur répond 503 et la console interdit l'émission d'un QR client. Aucun schéma URL personnalisé n'est activé. La durée de vie d'un QR client est de 30 minutes par défaut et plafonnée à 60 minutes par le canal d'administration.

## Effacement durable des données iOS

L'action d'effacement complet de l'application suit un ordre volontairement conservateur : CheckupAuto confirme d'abord la suppression serveur de l'installation et de ses bindings, puis l'application retire les deux entrées d'identité du Trousseau Apple, efface les véhicules conservés localement et supprime les rappels locaux programmés.

Après un effacement confirmé, un tombstone local bloque la recréation automatique de l'installation au démarrage ou au retour au premier plan, même si l'autorisation iOS de notifications est encore accordée. La réactivation doit résulter d'une action explicite : l'utilisateur choisit Réactiver Checkup Auto / Activer les rappels, ou consomme un nouveau claim véhicule valide.

Si la suppression serveur échoue, les données locales ne sont pas effacées et l'application demande de réessayer avec une connexion réseau. Si le serveur a confirmé la suppression mais que l'effacement du Trousseau échoue, le tombstone est déjà posé : l'application ne recrée pas silencieusement l'installation supprimée.

Cette fonction supprime les données de l'installation CheckupAuto et les données locales de l'application. Elle ne modifie pas les données réglementaires conservées dans Mercure.

## Inventaire autoritaire côté iPhone

L'application peut lire POST /api/mobile/inventory avec son identité d'installation. La réponse ne contient que des bindingId UUID opaques et la date d'échéance autoritaire lorsqu'elle est disponible. Aucun vehicleId, clientId, clientKind, immatriculation ou donnée Mercure brute n'est exposé.

La synchronisation autoritaire est indépendante du consentement APNs : un binding vérifié peut recevoir sa date serveur même lorsque l'utilisateur n'a pas activé les notifications push. Si le push distant n'est pas confirmé pour cet appareil, cette date autoritaire alimente le fallback local iOS. L'inventaire opaque vérifié est conservé localement pour permettre ce fallback hors ligne ; l'effacement complet de l'application le supprime avec le reste des données Checkup Auto.
