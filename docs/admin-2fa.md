# Authentification administrateur 2FA

Le back-office CheckupAuto utilise deux facteurs lorsqu'un TOTP a été enrôlé :

1. le compte HTTP Basic existant (`admin` + mot de passe privé) ;
2. un code TOTP RFC 6238 compatible Google Authenticator.

## Enrôlement

Après la première authentification Basic, l'administration affiche un écran bloquant si aucun TOTP n'est encore configuré.

Le parcours est :

1. cliquer sur **Configurer Google Authenticator** ;
2. scanner le QR code avec Google Authenticator ;
3. saisir le code à 6 chiffres ;
4. sauvegarder hors ligne les codes de récupération affichés une seule fois.

Le secret TOTP, la clé de signature de session et les hashes des codes de récupération sont stockés sous le répertoire privé CheckupAuto, jamais dans Git ni dans le HTML.

## Session 2FA

Après validation, le navigateur reçoit un cookie :

- `HttpOnly` ;
- `Secure` ;
- `SameSite=Strict` ;
- limité au chemin `/api/admin` ;
- durée maximale par défaut : 8 heures.

Le token de session est signé HMAC-SHA256 avec une clé privée locale. Il contient une empreinte de version du secret TOTP afin qu'une rotation invalide les anciennes sessions.

## Codes de récupération

Dix codes sont générés lors de l'enrôlement.

- ils sont affichés une seule fois ;
- seuls leurs hashes SHA-256 sont conservés ;
- chaque code est consommé définitivement lors de son utilisation ;
- Production Readiness passe en état dégradé si aucun code de récupération ne reste.

## Protection serveur

Une fois la 2FA configurée, toutes les API `/api/admin/*` exigent une session 2FA valide, à l'exception des endpoints nécessaires à l'enrôlement, à la vérification et à la déconnexion.

Les endpoints de vérification TOTP sont soumis au rate limiting Sentinel. Une erreur de code alimente également le compteur d'échecs d'authentification.

La page HTML du back-office peut être chargée après le Basic Auth, mais les données et mutations administratives restent inaccessibles sans session 2FA.

## Production Readiness

Le composant `admin_mfa` est critique :

- `configuration_required` si Google Authenticator n'est pas enrôlé ;
- `degraded` si la 2FA est active mais que les codes de récupération sont épuisés ;
- `ready` lorsque le TOTP est actif et au moins un code de récupération reste disponible.

L'activation publique reste fermée tant que ce composant n'est pas `ready`.

## Identifiant administrateur

L'identifiant HTTP Basic reste `admin`.

Le mot de passe n'est pas affiché dans l'interface ni dans les logs. Sur le serveur CheckupAuto, il reste stocké dans le répertoire privé sous `admin-password` avec permissions privées.
