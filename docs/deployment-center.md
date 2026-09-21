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
- le probe SSH ne modifie pas l'application distante ; il crée uniquement un répertoire de test temporaire pour vérifier écriture et symlinks, puis le supprime.

Le coffre par défaut est `~/.config/checkupauto-deployer`. Pour un service CheckupAuto, utiliser plutôt un chemin privé explicite via `CYBERCHECK_DEPLOYMENT_VAULT`.

## Définir une cible PlanetHoster

Exemple `target.json` :

```json
{
  "provider": "planethoster-n0c",
  "host": "ssh.example.net",
  "username": "checkupauto",
  "domain": "www.checkupauto.fr",
  "rootPath": "public_html",
  "authMode": "password"
}
```

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
- droit d'écriture sur la racine cible ;
- espace disque disponible.

## Générer le plan de release

Le plan est associé à un SHA Git exact :

```bash
python3 scripts/checkupauto-deployctl.py plan \
  --name production \
  --known-hosts ~/.config/checkupauto-deployer/known_hosts \
  --sha 0123456789abcdef0123456789abcdef01234567
```

Le layout cible est versionné :

```text
<root>/
  releases/
    <sha>/
  current -> releases/<sha>
  shared/
    data/
    private/
    security/
    logs/
```

Cela permet une bascule atomique de `current` et un rollback vers la release précédente.

## État PlanetHoster

Le code applicatif actuel utilise `ThreadingHTTPServer`. Un hébergement mutualisé PlanetHoster utilise un runtime Passenger Python. Le Deployment Center détecte Passenger mais refuse volontairement l'étape d'activation tant que l'adaptateur WSGI CheckupAuto n'est pas présent.

Ce garde-fou est intentionnel : le bouton d'installation ne doit jamais produire un site partiellement installé ou une API silencieusement indisponible.

Le chantier suivant consiste à fournir et tester l'adaptateur Passenger, puis à ajouter l'exécuteur `install/rollback` au-dessus du plan validé.
