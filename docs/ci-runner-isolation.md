# Isolation des runners CI (audit O-01, octobre 2026)

## Problème

Le runner auto-hébergé `[self-hosted, Linux, ARM64, internal]` sert aussi aux
déploiements de production. Tout job déclenché par `pull_request` y exécutait
du code de la branche proposée. Pour un événement `pull_request`, le fichier de
workflow lui-même provient de la tête de la PR : un garde-fou écrit dans le
dépôt ne peut donc **pas** empêcher à lui seul une personne ayant le droit
d'écriture de modifier le workflow et d'atteindre ce runner.

## Changements dans le dépôt

Les changements de workflows décrits ci-dessous sont appliqués (ils avaient d'abord été livrés sous forme de correctif, faute de portée `workflow` sur le jeton).


- `security-ci.yml` : les PR s'exécutent sur `ubuntu-24.04` (hébergé par
  GitHub). Les `push` sur `main` gardent le runner interne.
- `responsive-browser`, `site-preview`, `hostinger-staging-preflight`,
  `planethoster-test-current-main`, `payment-ci` et `3d-asset-ci` : une
  première étape, exécutée **avant** le checkout, refuse de continuer si le
  runner fait partie de la liste `vars.CHECKUPAUTO_PROTECTED_RUNNERS` (noms
  séparés par des virgules ou des espaces). Si la variable n'est pas définie,
  un avertissement est émis.
- `3d-asset-ci.yml` :
  - permissions par défaut `contents: read` et `persist-credentials: false` ;
  - la clé SSH provient uniquement du secret `CHECKUPAUTO_MAC_SSH_KEY` (plus
    aucune recherche dans `/root/.ssh`) ;
  - l'hôte, l'utilisateur et la clé d'hôte épinglée proviennent de
    `vars.CHECKUPAUTO_MAC_HOST`, `vars.CHECKUPAUTO_MAC_USER`,
    `vars.CHECKUPAUTO_MAC_KNOWN_HOSTS` ; `StrictHostKeyChecking=yes` ;
  - la publication du `.glb` se fait dans un job séparé `commit-glb`, sur un
    runner hébergé par GitHub, seul à disposer de `contents: write`.

## Actions côté runner (hors dépôt, obligatoires)

1. Placer le runner de production dans un **runner group** limité au workflow
   `production-deploy.yml@refs/heads/main` (Settings → Actions → Runner
   groups → « Selected workflows »), ou lui retirer le label `internal`.
2. Pour les PR qui ont réellement besoin d'un runner ARM64 interne, utiliser un
   runner **éphémère** (`--ephemeral`) sans accès aux secrets de production.
3. Définir `CHECKUPAUTO_PROTECTED_RUNNERS` (variable de dépôt) avec le nom du
   runner de production.
4. Définir les variables/secrets 3D ci-dessus ; sans eux, le job 3D échoue
   volontairement avec un message explicite.

# Limite de taille des requêtes (audit Q-02)

`passenger_wsgi.py` applique désormais une limite par route : 128 Kio par
défaut, 12 Mio uniquement pour `POST /api/customer/reports` (dépôt de rapports
de contrôle technique). Une requête plus grosse reçoit une `413` sans être lue.

Aucune directive `LimitRequestBody` n'a été ajoutée au `.htaccess` : sur un
hébergement mutualisé où elle n'est pas autorisée, elle provoquerait une
erreur 500 globale. Si l'hébergeur impose une limite Apache inférieure à
12 Mio, la relever côté panneau PlanetHoster.

# Rétention des données clients (audit R-01)

Règles automatiques ajoutées à `retention_enforcement.py` (exécutées par le
cycle existant) :

| Règle | Données | Durée |
|---|---|---|
| `customer_expired_sessions` | sessions client expirées | à l'expiration |
| `customer_password_transient` | inscriptions non confirmées sans identité (24 h), jetons consommés/expirés, compteurs anti-bruteforce (> 1 jour) | courte |
| `customer_oidc_flows` | états OIDC expirés | à l'expiration |
| `mobile_auth_tickets` | tickets mobiles expirés/consommés | à l'expiration |
| `customer_booking_abandoned` | brouillons de réservation abandonnés | 30 jours |

Règles configurables (nécessitent une politique opérateur avec justification) :

- `customer_inactive_accounts` : minimum 365 jours, recommandé 1095 jours
  (3 ans). Les comptes ayant un solde ou une valeur en attente dans le
  portefeuille ne sont jamais supprimés.
- `customer_booking_confirmed` : réservations confirmées ; **revue juridique
  obligatoire** (obligations comptables). Les lignes `reconciliation_required`
  ne sont jamais purgées automatiquement.

La suppression de compte (`customer_account_rights.erase`) efface désormais le
journal de réservation du compte et vérifie qu'il ne reste aucune ligne.

La télémétrie de sécurité (`security_telemetry`, 30 jours) est couverte par le
script existant `scripts/checkupauto-compliance-seed-technical-retention.py`,
à exécuter en production s'il ne l'a pas encore été.

# CI iOS (octobre 2026)

Depuis le 3 octobre 2026, `ios-core-ci.yml` exigeait un pool de Mac auto-hébergés
(`[self-hosted, macOS, ARM64, checkupauto, ios, ios-light|ios-heavy]`) qu'aucun
runner enregistré ne fournit : tous les jobs restaient en file d'attente puis
étaient annulés. Les jobs `swift` et `xcode` n'utilisent aucun secret ; ils
tournent désormais par défaut sur `macos-15` (hébergé par GitHub, Xcode 16).
XcodeGen est installé via Homebrew s'il manque.

Pour revenir aux Mac privés une fois le pool en ligne : variable de dépôt
`CHECKUPAUTO_IOS_SELF_HOSTED=true`. Attention : sur un dépôt privé, les minutes
macOS hébergées sont décomptées avec un multiplicateur (×10).

## Xcode 26 et smoke staging

- Les images `macos-15` utilisent Xcode 16 par défaut. Or `CheckupControlLiveActivityCoordinator.swift` appelle `Activity.request(style:alertConfiguration:start:)`, qui demande le SDK iOS 26. Sur les runners hébergés, les deux jobs sélectionnent donc la version stable la plus récente de `/Applications/Xcode_26*.app` via `DEVELOPER_DIR`.
- Le smoke de l'API de staging (`test.checkupauto.fr`, délai client de 8 s) est retenté trois fois avant d'échouer.

