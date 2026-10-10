# Audit d'octobre 2026 : constats Faible et Info

Ce document accompagne la PR « Audit sécurité : correctifs de sévérité Faible et Info ». Pour chaque constat, il indique ce qui est corrigé dans le dépôt, ce qui reste partiel et ce qui doit être fait hors du dépôt.

## Authentification mobile et clients

- **S-05, ticket mobile Google**
  - Le ticket ne contient plus de jeton de session, seulement l'identifiant du compte. La session est émise au moment de l'échange.
  - Si l'application envoie un `code_challenge` (PKCE S256) au démarrage, l'échange exige le `code_verifier` correspondant.
  - L'application iOS (`GoogleCustomerSignIn.swift`) envoie désormais ce challenge et ce verifier. **Ce code n'a pas été compilé ici**, faute de toolchain Xcode.
  - Les anciennes versions de l'application, qui n'envoient pas de challenge, restent acceptées jusqu'à ce que `CYBERCHECK_MOBILE_PKCE_REQUIRED=1` soit défini.
  - Les routes `/api/mobile/auth/exchange`, `/api/mobile/auth/apple` et `/api/mobile/auth/apple/nonce` ont une limite de débit Sentinel.
  - Le rappel en Universal Link https (à la place du schéma `checkupauto://`) reste à faire côté iOS.
- **S-06, Sign in with Apple natif**
  - Chaque nonce n'est accepté qu'une seule fois, ce qui empêche de rejouer un jeton volé avec son nonce.
  - Le serveur peut émettre des nonces : `POST /api/mobile/auth/apple/nonce`, valables 10 minutes et à usage unique.
  - L'e-mail fourni dans le corps de la requête est ignoré ; seule la revendication signée compte.
  - Pour que les nonces viennent obligatoirement du serveur, l'application doit appeler cette route avant `ASAuthorizationAppleIDRequest`. Ensuite, définir `CYBERCHECK_APPLE_SERVER_NONCE_REQUIRED=1`.
- **S-07, séparation des clés**
  - Le CSRF client utilise une sous-clé dérivée par HKDF.
  - Le CSRF de l'administration OIDC utilise une clé aléatoire dédiée (`$CYBERCHECK_PRIVATE_DIR/admin/csrf.key`) et ne dépend plus du mot de passe admin.
  - **Partiel :**
    - les index HMAC (e-mail, sujets OIDC) et le chiffrement des profils partagent toujours la clé maîtresse : les séparer demande une ré-indexation des données existantes ;
    - `payment_contract_http` utilise encore le mot de passe admin comme clé CSRF ; il n'a pas été modifié, car le code de paiement est hors périmètre.
- **S-08** : le fournisseur Microsoft, qui n'est pas exposé, échoue désormais fermé sans `email_verified`. `preferred_username` n'est plus jamais utilisé comme e-mail.
- **S-12** : le JSON injecté dans `<script>` échappe réellement `<`, `>` et `&`.

## Administration, serveur et intégrations

- **S-10** : les identifiants Basic sont comparés en octets. Un identifiant non ASCII reçoit une 401 au lieu de provoquer une exception.
- **S-11 (Info), limites de la Sentinelle** : elles sont documentées et inchangées.
  - Les signatures de requête ne sont pas une protection.
  - Le sel de l'empreinte client change chaque jour.
  - `init_db()` s'exécute à l'import.
- **S-13, webhooks Mercure**
  - Si Mercure envoie `X-CyberCheck-Timestamp`, la signature doit couvrir `timestamp + "." + corps` et l'horodatage doit tomber dans une fenêtre de ±5 minutes.
  - Chaque livraison n'est traitée qu'une fois : un journal anti-rejeu est conservé 30 jours.
  - Le format strict s'active avec `CYBERCHECK_MERCURE_WEBHOOK_TIMESTAMP_REQUIRED=1`, une fois Mercure adapté.
  - L'identifiant des conversions synthétiques ne dépend plus de `route`, ce qui limite à une seule conversion par intention.
- **S-15, coffre de déploiement**
  - La clé peut être placée hors du coffre, de deux façons :
    - `CYBERCHECK_DEPLOYMENT_VAULT_KEY_FILE=/chemin/hors/coffre` ;
    - `LoadCredential=deployment-vault.key:/chemin` dans l'unité systemd.
  - La lecture refuse les liens symboliques (`O_NOFOLLOW`).
  - Les écritures sont sérialisées par `flock`.
  - Migration : déplacer `master.key` vers le nouvel emplacement **avant** de définir la variable, sinon le coffre devient illisible (échec fermé).
- **S-16 (Info)** : la vérification des clés d'hôte SSH est conforme. L'avertissement explicite en cas de remplacement d'une empreinte n'est pas implémenté.
- **S-17**
  - L'en-tête `Server` ne révèle plus ni le produit ni Python.
  - **Restent à décider** :
    - `style-src 'unsafe-inline'`, qui demande de sortir les styles générés en Python ;
    - `img-src https:` ;
    - un endpoint `report-to` ;
    - HSTS `preload`, qui est un engagement difficile à annuler.
- **S-18**
  - Délai de socket de 30 s (`CYBERCHECK_HTTP_TIMEOUT_SECONDS`).
  - Plafond de 64 threads de traitement simultanés (`CYBERCHECK_HTTP_MAX_THREADS`). Au-delà, les connexions attendent dans la file du noyau.

## Dépendances, qualité, exploitation

- **D-01, partiel**
  - Les dépendances directes restent épinglées.
  - Un fichier de verrouillage avec empreintes (`pip-compile --generate-hashes`, puis `pip install --require-hashes`) n'a pas été introduit : il modifierait la construction de l'image et le déploiement PlanetHoster, qui ne peuvent pas être testés ici.
  - Il est aussi recommandé d'activer Dependabot ou Renovate.
- **D-02**
  - Avec le correctif O-01 (PR Moyenne), les PR s'exécutent sur `ubuntu-24.04`, qui fournit Python 3.12, la même version qu'en production.
  - Le runner interne garde son `python3` système.
- **Q-03, partiel**
  - Les connexions SQLite de la Sentinelle (`security_guard`, `security_behavior`, `security_alerts`) sont désormais fermées de façon déterministe.
  - Les autres modules utilisent encore le motif `with sqlite3.connect(...)`. La correction se fera au fil de l'eau, avec le même utilitaire.
- **Q-04** : chaque correctif de l'audit est couvert par un test comportemental (serveur HTTP réel, magasins SQLite réels, `app.js`/`consent.js` exécutés dans Node). Les anciens tests qui « greppent le source » n'ont pas été réécrits en masse.
- **Q-05, documenté** : le découpage en paquets et la suppression du code mort (modules `mercure_step*`, `mercure_vl_*`…) sont des refontes à planifier séparément.
- **Q-06** : l'annotation `VerifiedBookingIdentity` est importée sous `TYPE_CHECKING`.
- **Q-07**
  - `ruff.toml` contient une configuration minimale (E9, F63, F7, F82), sans règle de style.
  - L'étape CI correspondante est dans `docs/patches/o02-q07-workflow-pinning-ruff.patch` (voir plus bas).
- **R-02**
  - Le consentement cookies est lié à une empreinte de la liste des traceurs (`policyVersion`). Si la liste change, la question est reposée.
  - Les visiteurs déjà décidés verront le bandeau **une fois** après le déploiement, car leur choix ne porte pas encore de version.
  - Le bandeau prend le focus et le retient (Tab/Maj+Tab). Échap ferme le panneau des préférences ; sur le premier bandeau, Échap ne vaut pas décision. Le focus est restitué à la fermeture.
- **R-03 (Info)** : l'issue #147 n'a pas été modifiée. Les durées de conservation ajoutées par la PR Moyenne (R-01) y répondent en partie.
- **O-02** : épinglage par SHA de `actions/checkout` (v5.1.0) et de `actions/setup-python` (v6.3.0). Les SHA ont été vérifiés avec l'API GitHub. Voir le correctif ci-dessous.
- **O-03**
  - Image de base épinglée par empreinte (`python:3.12-slim@sha256:…`, relevée le 10/10/2026).
  - `.dockerignore` exclut désormais les secrets (`.admin-password`, `private/`, `*.pem`, `*.key`, `*.p8`, `*.p12`…).
  - Les paquets apt ne sont pas épinglés.
- **O-04**
  - `MemoryMax=1536M`, `TasksMax=512` et `SystemCallFilter=@system-service` ont été ajoutés.
  - Le déplacement de `/root/CyberCheck*` vers `/opt/checkupauto` et `/var/lib/checkupauto` est une migration serveur.
- **O-05 (Info)**
  - Ruff est ajouté par le correctif.
  - pip-audit, bandit, un seuil de couverture et gitleaks sur l'historique restent des pistes.
  - `/api/public/deployment-provenance` reste exposé par choix de conception.
- **F-01** : les données de planning Mercure sont échappées avant `innerHTML`.
- **F-02**
  - Le sélecteur de type de contrôle est un `group` de boutons `aria-pressed`, ce qui est cohérent avec leur rôle.
  - Les données structurées utilisent `AutoRepair`, avec `image`.
  - `geo`, `openingHoursSpecification` et `sameAs` demandent de nouveaux champs de configuration (valeurs réelles à fournir).
- **I-02 et I-03 (iOS)**
  - Non modifiés : impossible de compiler et de tester ici.
  - Stocker les immatriculations dans un fichier `NSFileProtectionComplete` ou dans le trousseau.
  - Vérifier `PrivacyInfo.xcprivacy` par rapport aux étiquettes App Store Connect.
- **H-02** : `.gitignore` couvre `.ruff_cache/`, `.mypy_cache/`, `.ci-venv/` et `node_modules/`.
- **H-01, H-03, H-04, H-05** : rien à corriger dans le code. Pour H-01, activer la suppression automatique des branches fusionnées et nettoyer les branches distantes.

## Correctif de workflows (portée `workflow` requise)

Le jeton utilisé pour cette PR ne peut pas modifier `.github/workflows/`. Il faut appliquer, **dans cet ordre**, avec un compte disposant de la portée `workflow` :

```bash
git apply docs/patches/o01-ci-runner-isolation.patch          # PR Moyenne
git apply docs/patches/o02-q07-workflow-pinning-ruff.patch    # cette PR
python -m unittest ci_runner_isolation_test workflow_pinning_test
git rm docs/patches/*.patch
git add -A .github/workflows ci_runner_isolation_test.py workflow_pinning_test.py
git commit -m "ci: isolation des runners, épinglage des actions et ruff (audit O-01, O-02, Q-07)"
```

L'étape ruff échoue tant que la PR Élevée (#687, correctif Q-01) n'est pas fusionnée, car elle détecte précisément le `NameError` corrigé par Q-01.
