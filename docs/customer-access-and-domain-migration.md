# Accès clients et migration CheckupAuto

## État vérifié le 30 septembre 2026

Le planning `https://rdv.checkupauto.fr/` répond et reste le service public de réservation. Le nouveau site fonctionne en préproduction sur `https://stage.179.198.210.187.sslip.io`.

L'API publique `/api/customer/providers` de la préproduction indique que Google, Apple et Microsoft ne sont pas configurés. Les parcours et le formulaire d'administration existent ; une connexion réelle n'est pas validée tant que les identifiants des applications fournisseurs ne sont pas installés.

Le nouvel espace client comprend le profil particulier/professionnel, la cagnotte et le parrainage, le rattachement du portefeuille à l'application iOS, l'import/analyse des procès-verbaux et leur téléchargement/suppression. Le lien de réservation mène explicitement au planning actuel. Les comptes et historiques Mercure ne sont pas fusionnés automatiquement par adresse e-mail.

## Connexions Google et Microsoft / Hotmail / Outlook

Chaque connexion utilise un état à usage unique, un nonce, PKCE et un cookie de navigateur `__Host-` propre à chaque état, Secure et HttpOnly. Le retour doit arriver sur l'origine qui a initié la connexion. Google/Microsoft utilisent SameSite=Lax ; Apple utilise SameSite=None pour son retour form_post. Les jetons sont vérifiés par signature, audience, émetteur et dates. Microsoft accepte les comptes personnels du tenant consommateur uniquement.

Ces connecteurs servent à l'identification. Ils ne demandent pas d'accès aux boîtes Gmail, Hotmail ou Outlook.

Créer ou utiliser les applications OAuth dans Google Cloud et Microsoft Entra. Microsoft doit autoriser les comptes Microsoft personnels ; les comptes professionnels Entra nécessitent une politique séparée. Enregistrer exactement les URI suivantes :

| Fournisseur | URI de préproduction |
|---|---|
| Google | `https://stage.179.198.210.187.sslip.io/auth/customer/google/callback` |
| Microsoft | `https://stage.179.198.210.187.sslip.io/auth/customer/microsoft/callback` |
| Apple | `https://stage.179.198.210.187.sslip.io/auth/customer/apple/callback` |

Installer les clientId/clientSecret via `/admin/customers.html`, protégé par la session administrateur, MFA et CSRF. Les secrets restent dans le fichier privé `customer/oidc.json`, mode 0600 ; ne jamais les ajouter à Git ni aux journaux. Apple exige un secret signé valide et son renouvellement.

Après configuration, vérifier séparément : consentement réel, retour au même navigateur, session, déconnexion, refus/annulation, et absence d'accès au compte avec un autre fournisseur partageant l'e-mail. Si le fournisseur n'émet pas une adresse e-mail utilisable, afficher un échec sans créer de compte incomplet.

## DNS : état et cible

Résolution publique Google DNS observée ; elle ne remplace pas un export intégral de la zone autoritative.

| Entrée | État observé | Cible pendant les essais |
|---|---|---|
| NS | nsa.n0c.com, nsb.n0c.com, nsc.n0c.com | Conserver les serveurs de noms actuels |
| `checkupauto.fr` A | 185.221.181.53, TTL environ 14400 | 179.198.210.187 après validation HTTPS |
| `www` CNAME | checkupauto.fr | Conserver |
| `rdv` A | 185.124.200.66, TTL 3600 | Conserver le planning actuel |
| `rdv2` | NXDOMAIN | Créer ultérieurement après protection des essais |
| MX | priorité 0, mail.checkupauto.fr ; A indépendant 185.221.181.53 | Conserver |
| AAAA principal / RDV | Aucun observé | Ne pas ajouter avant validation IPv6 |
| CAA principal | Aucun observé | Vérifier la zone et la politique ACME avant émission |

Ne pas remplacer les NS par ceux du nouvel hébergeur : les changements web peuvent être réalisés dans la zone existante. Exporter la zone complète, notamment MX, A/CNAME mail, SPF, DKIM, DMARC, SRV et sous-domaines. Si mail dépend du domaine principal, le rendre indépendant avant de changer l'adresse web, en conservant sa cible de messagerie actuelle.

## Façade publique temporaire

`deploy/hostinger/public-redirect.compose.yml` définit un service distinct sur le réseau Coolify, pour `checkupauto.fr` et `www.checkupauto.fr`. Il redirige en HTTP 302 vers `https://rdv.checkupauto.fr/`, sans transmettre chemins, requêtes ni références. Les chemins sensibles et POST reçoivent 404. Les URLs ne sont pas journalisées. La redirection est temporaire et non mise en cache.

Les routeurs HTTP et HTTPS passent tous deux par le même contrôle des méthodes et chemins ; aucune redirection de schéma ne précède ce contrôle.

Le service utilise le résolveur ACME Let's Encrypt déjà utilisé par la préproduction. La configuration seule ne prouve pas qu'un certificat a été émis. Pour éviter toute alerte pendant la bascule, pré-émettre un certificat valide avec DNS-01 via le contrôle de la zone, ou faire servir le défi HTTP-01 par l'ancien hébergeur vers le nouveau, puis vérifier la chaîne et les deux noms via l'adresse du nouveau serveur avant changement DNS. Ne jamais désactiver la validation TLS.

Déployer la façade séparément du nouveau site, vérifier la redirection et l'isolation des callbacks, puis abaisser le TTL et attendre l'ancien TTL. Modifier seulement les enregistrements web nécessaires. Vérifier les résolutions autoritatives et publiques, les certificats, les réservations existantes et la messagerie. Garder l'ancien hébergement disponible pendant la propagation et le retour arrière ; restaurer l'ancien A si une vérification échoue.

## RDV2 et planning existant

Le planning actuel est hébergé séparément : déplacer son DNS vers le VPS ne migre ni ses données ni ses fonctions. La conservation de `rdv` assure la continuité pendant les tests du nouveau site. Une migration réelle du planning nécessitera les accès et capacités du fournisseur Mercure, un export/une intégration supportés, ainsi qu'une validation des créneaux, réservations, comptes et notifications. Ne pas utiliser un proxy arbitraire qui pourrait casser les sessions ou le paiement.

Avant de créer `rdv2.checkupauto.fr`, prévoir une protection d'accès effective (liste d'adresses autorisées ou passerelle d'authentification) ; noindex seul ne protège pas les essais. Choisir une origine définitive pour les callbacks OAuth et Payline, mettre à jour leurs listes autorisées et tester l'application iOS sur cette origine. Une authentification Basic globale doit être évaluée pour sa compatibilité avec l'application et les callbacks bancaires avant activation.

Les tests de paiement actuels utilisent le simulateur ; ils ne valident pas encore un échange bancaire Payline réel. Les paiements réels restent désactivés. Le contrat et les clés de bac à sable Payline restent nécessaires avant une recette bancaire complète.
