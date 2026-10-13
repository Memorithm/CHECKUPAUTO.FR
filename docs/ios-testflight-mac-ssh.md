# TestFlight — liaison SSH avec le Mac mini

Le job `iOS TestFlight Delivery` part du runner Linux ARM64 `checkupauto-thor-arm64-02` sur l'hôte `tarek`. Ce n'est pas nécessairement la machine Debian utilisée pour les diagnostics manuels : clés, `$HOME` et résolution DNS sont propres à **chaque hôte**.

## Résolution de la destination

Le workflow teste le port TCP 22, sans ouvrir de session, sur les destinations suivantes, dans cet ordre :

1. `CHECKUPAUTO_MAC_HOST` (variable GitHub Actions facultative ; défaut : `Mac-mini-de-tarek.local`).
2. `CHECKUPAUTO_MAC_FALLBACK_IPV4` (défaut : `192.168.0.27`, interface `en0` constatée le 13/10/2026).
3. `CHECKUPAUTO_MAC_SECONDARY_IPV4` (défaut : `192.168.0.17`, interface `en1` constatée le 13/10/2026).

La première destination accessible est transmise à toutes les étapes du job par `GITHUB_ENV`. Les adresses doivent être actualisées dans les variables du dépôt si l'adressage LAN change. Un port TCP joignable **ne prouve pas** une authentification SSH réussie.

## Identité de déploiement

Le workflow exige une connexion SSH non interactive par clé. Sa priorité reste la clé privée fournie par le secret GitHub `CHECKUPAUTO_MAC_SSH_KEY`, puis les identités configurées localement sur le runner. Il n'accepte pas les mots de passe et n'imprime pas les clés.

Si le contrôle de port réussit mais que le job « Resolve authorized Mac SSH identity » échoue :

- Vérifier sur le runner **`tarek`** que la clé privée correspond à une clé publique déjà autorisée pour `tarek` sur le Mac mini.
- Préférer le secret GitHub Actions `CHECKUPAUTO_MAC_SSH_KEY` configuré par un administrateur du dépôt, sans insérer la clé privée dans un commit, un ticket ou un journal.
- Garder `BatchMode=yes`, `IdentitiesOnly=yes` et le contrôle de clé d'hôte en place. Le prochain durcissement recommandé est l'épinglage explicite de la clé d'hôte SSH à partir d'une empreinte vérifiée hors bande.

La validation de ce canal SSH ne prouve ni la présence des identifiants App Store Connect ni le succès d'un téléversement TestFlight. Le workflow teste ensuite séparément ces conditions.
