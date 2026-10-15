# Rotation du mot de passe administrateur

## Accès

Après déploiement de cette modification :

- URL : `https://test.checkupauto.fr/admin/#admin-password`.
- Menu : **Mot de passe admin**.
- Identifiant HTTP Basic inchangé : `admin`.

La page demande l'ancien mot de passe, le nouveau et sa confirmation.
La session 2FA configurée et un jeton CSRF lié aux identifiants du navigateur
sont requis avant toute modification. Le bouton n'enregistre rien dans les
réglages SEO et ne met jamais les mots de passe dans l'URL.

## Côté serveur

- Le mot de passe reste dans `CYBERCHECK_PRIVATE_DIR/admin-password`.
- Le fichier privé existant est contrôlé (fichier régulier, propriétaire du
  processus serveur, permissions 0600, pas de lien symbolique).
- Chaque requête HTTP Basic relit ce fichier. Un ancien mot de passe est rejeté
  immédiatement par chaque worker, même sans redémarrage.
- La rotation est verrouillée inter-processus et réalisée par écriture temporaire
  0600, `fsync`, `os.replace`, puis `fsync` du répertoire.
- La modification exige l'ancien secret et la confirmation exacte. Les valeurs
  sont purgées du formulaire côté client après chaque tentative.
- La clé de session MFA est renouvelée après rotation, invalidant les anciennes
  sessions. Le navigateur reçoit également l'instruction de supprimer son cookie.
- Les jetons CSRF du menu Paiements sont dérivés à partir du mot de passe courant
  pour rester cohérents après rotation dans tous les workers.
- Sentinel limite les appels de rotation et de récupération CSRF.
- Les endpoints n'exposent aucune donnée secrète, y compris dans les messages
  d'échec. La longueur minimale est de 8 caractères.

## Mise en production

La fusion d'une PR ne modifie pas à elle seule le mot de passe en cours sur
l'hébergement. Ne jamais écrire le nouveau mot de passe dans GitHub, les
fixtures, les workflows, les logs, les paramètres publics ou une issue.

Vérifier successivement : CI Security verte sur le SHA exact ; mise en ligne
d'une release épinglée via RemoteOps ; accès à la rubrique sous le compte
administrateur avec MFA ; changement par le formulaire HTTPS ; vérification
que l'ancienne connexion HTTP Basic échoue ; nouvelle connexion HTTP Basic +
MFA réussie. Les navigateurs mettant en cache Basic peuvent nécessiter une
fermeture complète de l'onglet ou une fenêtre privée.

Pas de changement silencieux du mot de passe du serveur à la fusion. En cas
de problème d'accès ou de fichier privé non conforme, suspendre l'opération
et traiter via le plan de contrôle autorisé plutôt que de créer une route
d'initialisation publique ou de placer le secret dans une CI.
