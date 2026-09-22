# Back-office Paiements — fiche du contrat Payline / Monext

## Fonction livrée

Le menu **Paiements** du back-office ouvre `/admin/payments.html`. Son API privée est `/api/admin/payments/contract` (GET/POST). L'écran permet de saisir puis modifier les quinze champs de la fiche d'acquisition : accepteur, acquéreur et références 3-D Secure.

Les identifiants sont des chaînes de caractères : les zéros initiaux sont préservés. Les champs vides sont autorisés pour une fiche en cours de saisie. Les contrôles portent sur les formats, pas sur l'existence ou l'activation du contrat auprès de la banque.

La saisie manuelle met à jour les champs explicitement transmis. Un import `import_missing` ne remplit que les champs vides **déjà enregistrés**. Il ne remplace pas les modifications manuelles, ne s'exécute pas au démarrage du site et n'est pas rejoué silencieusement. Après import, tous les champs restent modifiables manuellement. Une seconde importation identique n'ajoute aucune révision.

Le document importé doit contenir exactement `schemaVersion` (entier 1), `provider` (`payline_monext`) et `fields` (dictionnaire de champs connus et textuels). La limite est 32 Kio. La fiche réelle et l'image du commerçant restent hors Git ; les tests ne contiennent que des données synthétiques.

## Accès et confidentialité

L'API appelle l'authentification administrateur et la validation de session MFA existantes avant d'accéder au stockage. Elle ne change pas la politique globale d'inscription MFA : si la 2FA n'est pas configurée, le comportement antérieur du back-office reste applicable. Une mise en production doit donc vérifier la configuration effective de la 2FA.

Les écritures exigent un jeton CSRF lié aux en-têtes d'authentification et de session, limité dans le temps, obtenu avec le GET authentifié. Le contrôle d'origine existant et `Sec-Fetch-Site` sont également vérifiés. L'API refuse les corps non JSON, les corps trop volumineux, l'encodage de transfert, les clés JSON dupliquées et les paramètres d'URL. Les réponses bénéficient de `Cache-Control: no-store` et des en-têtes de sécurité existants.

La fiche est stockée sous `CYBERCHECK_PRIVATE_DIR/payments` (par défaut `/root/CyberCheckPrivate/payments`), hors du code et de la racine Web. Le répertoire est privé et les fichiers sont limités à leur propriétaire. `contract.enc` chiffre les champs et l'audit avec AES-GCM ; `contract.key` contient la clé locale. Sauvegarder les deux dans une sauvegarde privée protégée, et tester leur restauration. Ce chiffrement ne protège pas contre un administrateur système disposant à la fois du fichier et de sa clé.

Une clé manquante ne sera pas recréée si une fiche chiffrée existe déjà. Un fichier corrompu ou des permissions publiques provoquent un refus ; aucune réinitialisation silencieuse. Le verrou fichier sérialise les mises à jour concurrentes. La révision attendue évite qu'un deuxième onglet écrase des modifications plus récentes ; le serveur retourne HTTP 409 et l'interface conserve la saisie non enregistrée.

L'audit conserve au maximum les cent dernières modifications (les vingt dernières sont affichées), avec révision, horodatage, mode et noms des champs modifiés. Il ne conserve pas les anciennes valeurs et ne prétend pas être un journal d'audit inviolable ou un historique exhaustif. Le compte administrateur est actuellement partagé : aucune attribution à une personne nominative n'est revendiquée.

## Import automatisé privé

`payment_contract_cli.py` importe le même schéma depuis un fichier privé hors du code, sans imprimer les valeurs. Il exige un fichier régulier non lié symboliquement et sans accès groupe/autres. `--revision` doit correspondre à la révision actuelle ; utiliser 0 uniquement pour une fiche encore vide.

Exemple développeur, à adapter aux chemins privés du déploiement :

```bash
python3 payment_contract_cli.py \
  --file /srv/checkupauto-private/fiche-payline.json \
  --store /srv/checkupauto-private/payments \
  --revision 0
```

L'exemple ne crée ni compte bancaire, ni contrat chez le prestataire. Exécuter l'import sous le même utilisateur de service que le back-office pour conserver les contrôles de propriété. Le fichier d'import n'est jamais à déposer dans `public`, `assets`, `admin` ou une archive publiquement servie.

## Ce qui n'est pas activé

Ce menu traite la fiche d'acquisition, **pas les clés API**. `merchantId` API, `accessKey`, `contractNumber`, secrets PayPal et données de carte sont refusés par ce schéma. La future configuration des connecteurs devra disposer de sa propre gestion des secrets ; aucune valeur TPE/BIN/Merchant ID Mastercard n'est convertie en identifiant API.

Les indicateurs `contractVerified`, `apiCredentialsConfigured`, `checkoutBound` et `livePaymentsEnabled` restent faux. Ils décrivent les capacités de cette tranche, pas le résultat d'une inspection des autres coffres ou d'un appel à la banque. Le choix Payline / Monext est confirmé, mais la simple sauvegarde de la fiche ne vérifie pas les identifiants API ni le contrat distant.

L'édition ne déclenche aucun appel fournisseur, paiement, remboursement, notification, modification de réservation Mercure ou changement de configuration d'hébergement. PayPal direct reste séparé. Monetico n'est pas le connecteur sélectionné pour ce contrat.

## Tests et déploiement

```bash
python3 -m unittest -v payment_contract_test payment_contract_routes_test payment_contract_frontend_test
```

Les tests de routes exercent le véritable `admin_server.Handler` via HTTP local, sur un stockage temporaire ; ils ne contournent que le filtre de requêtes global pour isoler les contrats d'authentification/CSRF/persistance. Les tests de chiffrement, concurrence, import, erreurs et formats ne nécessitent aucun accès bancaire. Le test de syntaxe JavaScript est exécuté lorsque Node.js est disponible, comme sur le runner existant.

Le contrôle fonctionnel local de l'éditeur utilise Chromium, le JavaScript de l'écran et le vrai stockage chiffré, mais un transport HTTP simulé. Ce contrôle n'est ni une recette sur iPhone, ni une preuve de déploiement de l'application complète.

La démonstration actuellement servie sur le T430 est un HTML autonome. Elle ne reçoit pas ce menu par une simple fusion GitHub. Le menu devient utilisable après déploiement du backend et des fichiers `admin` sur un environnement authentifié. Ne pas exposer le fichier d'import bancaire sur le tunnel de démonstration. Aucun changement d'OwnCloud/8080 ni des tunnels existants n'est nécessaire pour cette modification de code.
