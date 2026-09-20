# Chaîne Release iOS Checkup Auto

La Release iOS est pilotée par `ios_release_runner.py`. Le runner refuse une archive réelle hors macOS, sur un arbre Git sale, sur une branche différente de `main`, ou si `HEAD` ne correspond pas exactement à `origin/main`.

Aucun secret Apple n'est stocké dans Git. L'équipe Apple est fournie au runtime via `CHECKUPAUTO_APPLE_TEAM_ID`; les options d'export sont fournies par un plist externe au dépôt. L'autorisation de mise à jour des profils n'est activée que si `CHECKUPAUTO_ALLOW_PROVISIONING_UPDATES=1`.

## 1. Préflight du Mac

Depuis la racine du dépôt :

```bash
python3 ios_release_runner.py preflight --toolchain-status
python3 ios_release_runner.py preflight
```

Le premier appel inventorie `xcodegen`, `xcodebuild`, `xcrun` et `codesign`. Le second génère le projet dans un répertoire temporaire et valide les réglages Release réellement résolus par Xcode.

## 2. Tests iOS

```bash
python3 ios_release_runner.py test
```

Le runner sélectionne automatiquement un simulateur iPhone disponible dans le runtime iOS le plus récent, puis lance les XCTest avec la signature désactivée pour le simulateur.

## 3. Archive signée

Configurer l'identifiant d'équipe uniquement dans le shell ou dans le stockage privé de la machine :

```bash
export CHECKUPAUTO_APPLE_TEAM_ID='XXXXXXXXXX'
python3 ios_release_runner.py archive
```

Si Xcode doit pouvoir créer ou actualiser les profils de provisioning :

```bash
export CHECKUPAUTO_ALLOW_PROVISIONING_UPDATES=1
python3 ios_release_runner.py archive
```

Après l'archive, le runner relit l'application signée et refuse la Release si le bundle ID, l'environnement APNs, Associated Domains ou l'Application Identifier signé ne correspondent pas au contrat Checkup Auto.

Les artefacts sont écrits hors du dépôt dans `~/Library/Developer/CheckupAutoRelease/<commit>/`.

## 4. Export ou envoi App Store Connect

Le fichier `ExportOptions.plist` doit rester hors Git et être construit avec les options supportées par la version de Xcode installée sur le Mac.

Export local :

```bash
python3 ios_release_runner.py export --export-options /chemin/prive/ExportOptions.plist
```

Si le plist demande explicitement une destination `upload`, le runner refuse l'opération tant que l'intention n'est pas confirmée :

```bash
python3 ios_release_runner.py export \
  --export-options /chemin/prive/ExportOptions.plist \
  --allow-upload
```

Cette garde empêche qu'un simple test local déclenche accidentellement une soumission App Store Connect.

## Garanties

- aucune clé APNs, clé App Store Connect, session Xcode ou mot de passe n'est lu depuis Git ;
- `main` doit être propre et identique à `origin/main` pour toute exécution réelle ;
- le projet Xcode est généré dans un répertoire temporaire, donc aucun `.xcodeproj` généré n'est commité ;
- les XCTest précèdent obligatoirement l'archive ;
- une archive signée est relue avant tout export ;
- l'upload nécessite un consentement CLI explicite.
