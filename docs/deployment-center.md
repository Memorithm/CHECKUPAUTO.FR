# Deployment Center CheckupAuto

Le Deployment Center prépare l'installation et les mises à jour de CheckupAuto sur un hébergeur distant sans inscrire de secret dans Git.

## Profils fournis

| Profil | Port SSH par défaut | Runtime attendu |
| --- | ---: | --- |
| `planethoster-n0c` | 5022 | Passenger Python |
| `planethoster-cpanel` | 2908 | Passenger Python |
| `generic-ssh` | 22 | Passenger ou systemd détecté |
| `linux-systemd` | 22 | systemd |

Les ports sont des valeurs de départ. Un port explicitement fourni dans la cible est toujours prioritaire.

## Modèle de sécurité

Le Deployment Center est fail-closed :

- `StrictHostKeyChecking=yes` est imposé ;
- un fichier `known_hosts` préalablement approuvé est obligatoire ;
- un mot de passe SSH n'est jamais placé dans les arguments du processus ;
- les mots de passe et chemins de clés sont stockés dans un coffre AES-GCM hors du dépôt ;
- le coffre est créé avec un répertoire `0700` et des fichiers `0600` ;
- les plans et listes de cibles n'exposent jamais le credential ;
- le probe SSH ne modifie pas l'application distante ; il crée uniquement un répertoire de test temporaire pour vérifier écriture et symlinks, puis le supprime ;
- sur hébergement mutualisé, releases, bases, credentials, état sécurité, baseline d'intégrité et logs restent hors de la racine Web.

Le coffre par défaut est `~/.config/checkupauto-deployer`. Pour un service CheckupAuto, utiliser plutôt un chemin privé explicite via `CYBERCHECK_DEPLOYMENT_VAULT`.

## Définir une cible PlanetHoster

Le profil PlanetHoster sépare deux racines relatives au HOME :

- `.checkupauto` : racine privée de déploiement ;
- `public_html` : racine Web Passenger.

Exemple `target.json` :

```json
{
  "provider": "planethoster-n0c",
  "host": "ssh.example.net",
  "username": "checkupauto",
  "domain": "www.checkupauto.fr",
  "rootPath": ".checkupauto",
  "webRootPath": "public_html",
  "authMode": "password"
}
```

`rootPath` ne doit jamais être égal à `webRootPath` ni être situé dessous. Les anciens profils enregistrés avec `rootPath: "public_html"` doivent être remplacés avant tout déploiement ; le validateur les refuse désormais.

Valider sans enregistrer de secret :

```bash
python3 scripts/checkupauto-deployctl.py validate --target target.json
```

Enregistrer la cible. Le mot de passe est lu sur stdin et n'apparaît pas dans la ligne de commande :

```bash
printf '%s\n' "$PLANETHOSTER_PASSWORD" |
  python3 scripts/checkupauto-deployctl.py save \
    --name production \
    --target target.json \
    --password-stdin
```

Pour une clé SSH :

```bash
python3 scripts/checkupauto-deployctl.py save \
  --name production \
  --target target-key.json \
  --identity-file ~/.ssh/checkupauto_planethoster
```

## Tester la connexion et l'hébergement

Après avoir approuvé la clé hôte dans un fichier `known_hosts` dédié :

```bash
python3 scripts/checkupauto-deployctl.py probe \
  --name production \
  --known-hosts ~/.config/checkupauto-deployer/known_hosts
```

Le probe rapporte notamment :

- version Python ;
- présence de Node ;
- Passenger ;
- systemd ;
- cron ;
- support des symlinks ;
- droit d'écriture sur la racine privée de déploiement ;
- droit d'écriture sur la racine Web lorsqu'elle est distincte ;
- espace disque disponible.

## Générer le plan de release

Le plan est associé à un SHA Git exact :

```bash
python3 scripts/checkupauto-deployctl.py plan \
  --name production \
  --known-hosts ~/.config/checkupauto-deployer/known_hosts \
  --sha 0123456789abcdef0123456789abcdef01234567
```

Le layout mutualisé est séparé :

```text
$HOME/
  .checkupauto/
    releases/
      <sha>/
    current -> releases/<sha>
    shared/
      data/
      private/
      security/
      integrity/
      logs/
  public_html/
    # point d'entrée Passenger uniquement
```

Les secrets, bases SQLite et états opérationnels ne doivent donc pas être copiés sous `public_html`. La bascule de release reste atomique via le lien privé `current` et permet un rollback vers la release précédente.

## Runtime PlanetHoster

CheckupAuto dispose d'un pont WSGI Passenger qui réutilise le `Handler` HTTP existant derrière un serveur loopback interne. L'adresse IP cliente n'est transmise à Sentinel qu'avec un jeton proxy aléatoire interne ; les headers externes de même nom sont supprimés par le pont.

Les workers persistants ne sont jamais démarrés dans les processus Passenger. Sur hébergement mutualisé, les tâches périodiques sont exécutées par `scripts/checkupauto-shared-tick.py` via CRON avec un verrou fichier non bloquant. Le tick couvre notamment la purge des tests de réservation, ReminderEngine, la synchronisation mobile autoritaire, les rappels mobiles, les avis Google et le retry des alertes.

Le profil PlanetHoster n'est déclaré prêt que si le diagnostic confirme :

- Python 3.11 ou supérieur ;
- Passenger ;
- CRON ;
- symlinks ;
- racine privée de déploiement accessible en écriture ;
- racine Web accessible en écriture ;
- au moins 1 Gio libre ;
- pont Passenger/WSGI présent dans la release ;
- scheduler mutualisé présent dans la release.

Le runtime mutualisé utilise les chemins privés configurables suivants :

```text
CYBERCHECK_DATA_DIR=$HOME/.checkupauto/shared/data
CYBERCHECK_PRIVATE_DIR=$HOME/.checkupauto/shared/private
CYBERCHECK_SECURITY_DIR=$HOME/.checkupauto/shared/security
CYBERCHECK_INTEGRITY_DIR=$HOME/.checkupauto/shared/integrity
CYBERCHECK_GSC_CREDENTIALS_PATH=$HOME/.checkupauto/shared/private/gsc-service-account.json
CYBERCHECK_SITE_CONFIG_PATH=$HOME/.checkupauto/shared/data/site-config.json
```

## Installation, mise à jour et rollback en une commande

Les commandes `install` et `update` exécutent la même chaîne vérifiée : nouveau probe SSH, validation des capacités, création d'une archive depuis le SHA Git exact, staging dans une release privée neuve, création du venv et installation des dépendances, compilation Python, activation atomique, configuration Passenger/CRON puis vérification HTTPS et Production Readiness. La release active n'est pas modifiée si le staging échoue ; une erreur pendant l'activation déclenche le rollback automatique décrit dans `docs/deployment-activation.md`.

Le SHA doit être un commit exact déjà présent dans le dépôt Git local :

```bash
python3 scripts/checkupauto-deployctl.py install \
  --name production \
  --known-hosts ~/.config/checkupauto-deployer/known_hosts \
  --sha 0123456789abcdef0123456789abcdef01234567
```

Pour une mise à jour, la commande est identique à l'exception du verbe :

```bash
python3 scripts/checkupauto-deployctl.py update \
  --name production \
  --known-hosts ~/.config/checkupauto-deployer/known_hosts \
  --sha 89abcdef0123456789abcdef0123456789abcdef
```

Le résultat JSON ne restitue ni credential, ni chemin privé de release. Il fournit le SHA activé, le SHA précédent, l'empreinte de l'archive, le nombre de fichiers et l'état Production Readiness borné.

Un rollback explicite ne reconstruit ni ne retransfère de code : il ne peut cibler qu'une release déjà staged et vérifiée sur l'hébergeur, puis réutilise exactement le même chemin d'activation et de contrôle post-bascule :

```bash
python3 scripts/checkupauto-deployctl.py rollback \
  --name production \
  --known-hosts ~/.config/checkupauto-deployer/known_hosts \
  --sha 0123456789abcdef0123456789abcdef01234567
```

Les profils enregistrés conservent désormais explicitement une éventuelle `webRootPath` personnalisée lors de leur rechargement ; le contrôleur ne retombe plus silencieusement sur `public_html` pour une cible déjà enregistrée avec une autre racine Web.

## Bootstrap du secret administrateur

Lors d’une première installation sur un hébergement vierge, CheckupAuto doit disposer de `shared/private/admin-password` avant le démarrage Passenger et avant le contrôle Production Readiness.

Depuis l’interface d’administration, le Deployment Center réutilise automatiquement le mot de passe administrateur du CheckupAuto courant. Il est transmis uniquement dans le flux SSH chiffré, n’est jamais placé dans les arguments de processus, n’est pas ajouté aux jobs ou à l’historique, et est écrit à distance en mode `0600` uniquement si le fichier n’existe pas déjà.

Les mises à jour et rollback conservent le credential distant existant. Un fichier existant sous forme de symlink ou contenant une valeur invalide fait échouer l’activation.

En mode CLI autonome, un secret initial peut être fourni via stdin :

```bash
printf '%s\n' "$CHECKUPAUTO_ADMIN_PASSWORD" |
  python3 scripts/checkupauto-deployctl.py install \
    --name production \
    --known-hosts ~/.config/checkupauto-deployer/known_hosts \
    --sha 0123456789abcdef0123456789abcdef01234567 \
    --admin-password-stdin
```

## Utilisation depuis l’administration

Le panneau **Administration → Déploiement** permet de piloter le Deployment Center sans terminal :

1. choisir le profil PlanetHoster ;
2. saisir serveur, port, utilisateur, domaine et credential ;
3. enregistrer la cible dans le coffre AES-GCM privé ;
4. scanner la clé hôte SSH ;
5. comparer l’empreinte SHA-256 avec celle communiquée par l’hébergeur puis l’approuver ;
6. lancer le diagnostic de compatibilité ;
7. construire le plan de release ;
8. cliquer sur **Installer** ou **Mettre à jour** ;
9. suivre le job asynchrone jusqu’au contrôle Production Readiness ;
10. utiliser **Rollback** avec le SHA d’une release déjà staged si nécessaire.

Le mot de passe SSH n’est jamais renvoyé au navigateur après l’enregistrement. Une valeur vide lors de l’édition conserve le credential déjà présent dans le coffre. La clé hôte n’est pas approuvée automatiquement : le scan et la confirmation sont deux opérations distinctes, et la confirmation rescane le serveur avant d’écrire `known_hosts`.

Les opérations d’installation sont sérialisées par un verrou fichier inter-processus. Deux workers Passenger ou deux onglets administrateur ne peuvent donc pas activer simultanément deux releases différentes.

## Gestion des mises à jour

Le Deployment Center ne suppose jamais que la cible distante exécute le dernier SHA local. L’action **Vérifier les mises à jour** lit par SSH le lien `current` et l’inventaire des releases distantes dont le marqueur `.checkupauto-release.json` est vérifié.

L’état est classé ainsi :

- `not_installed` : aucune release active ;
- `up_to_date` : la cible exécute exactement le SHA Git local courant ;
- `update_available` : le SHA distant est un ancêtre Git du SHA local courant ;
- `remote_ahead` : la cible distante est plus récente que le checkout local ;
- `diverged` : les historiques ne permettent pas une mise à jour automatique sûre.

Le bouton **Mettre à jour** n’est activé que dans l’état `update_available`. Les états `remote_ahead` et `diverged` imposent une intervention explicite plutôt qu’un écrasement automatique.

Les candidats de rollback affichés par l’administration proviennent uniquement des répertoires distants dont le SHA, le marqueur et l’empreinte de release ont déjà été vérifiés ; un SHA arbitraire saisi par l’interface reste ensuite revalidé côté serveur avant activation.

## Sauvegardes avant mise à jour

Avant toute bascule d'une installation existante — mise à jour ou rollback — le Deployment Center crée un snapshot privé sous `shared/backups`.

Les bases SQLite détectées dans `shared/data` et `shared/security` sont copiées avec l'API SQLite backup puis contrôlées par `PRAGMA quick_check`. Le fichier `site-config.json`, lorsqu'il existe, est également copié avec son empreinte SHA-256. Si cette sauvegarde échoue, le lien `current` n'est pas modifié.

Après validation HTTPS de l'instance exacte et passage du Production Readiness, une rétention bornée est appliquée :

- 5 releases vérifiées au maximum ; la release active et la release précédente sont toujours conservées ;
- 12 snapshots de sauvegarde vérifiés ;
- suppression des répertoires de staging `.incoming-*` abandonnés depuis plus de 24 heures ;
- aucune suppression automatique d'un répertoire de release dont le marqueur n'est pas vérifié.

Le snapshot et les compteurs de nettoyage sont ajoutés à `deployment-history.jsonl`. Un échec de nettoyage après une activation déjà vérifiée n'annule pas la release ; il reste visible dans l'historique pour correction ultérieure.

Pour préserver les rollbacks vers des releases historiques, l'activation peut exécuter le helper de sécurité d'update depuis la release cible ou, si elle est trop ancienne pour le contenir, depuis la release actuellement active.

## Source de mise à jour

Une installation PlanetHoster est une release packagée : elle contient le marqueur `.checkupauto-release.json`, mais pas le répertoire `.git`.

Le back-office distingue donc deux modes :

- `git_checkout` : SHA Git local vérifié et construction de nouvelles releases autorisée ;
- `packaged_release` : SHA de la release lisible, mais construction Install/Update interdite.

Dans le second cas, le site continue à afficher sa version et peut lire l'inventaire distant ainsi qu'effectuer un rollback vers une release déjà vérifiée. En revanche, il n'affiche jamais une release packagée comme source de build valide et ne prétend pas être « à jour » par simple comparaison avec elle-même.

Cette séparation évite qu'une instance PlanetHoster sans dépôt Git tente une mise à jour incomplète. Un futur mode de mise à jour autonome devra fournir explicitement une source de release vérifiée avant d'activer Install/Update.

