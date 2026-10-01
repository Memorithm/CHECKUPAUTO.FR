# Accès clients et migration CheckupAuto

## Préproduction au 1er octobre 2026

Le site de test est installé sur PlanetHoster à `https://test.checkupauto.fr`. Le déploiement source `d9edb1e7dea1397dae239bb58f4639ad0ba3c166` est vérifié par RemoteOps (PR #130), après la restauration privée de la session Mercure (PR #129). Les CGV de substitution `test-2026-10-01` et leur menu d’import sont disponibles.

La réservation doit conserver son parcours dans CheckupAuto ; Mercure sera chargé du paiement lorsque cette capacité sera activée et son interface vérifiée. L’inspection publique du 1er octobre montre `isPaiementLigne=false` et uniquement « Valider et payer en centre ». Un paramètre `iframe` dans le code Mercure ne prouve ni le fonctionnement du paiement intégré ni une confirmation serveur supportée. Aucun paiement réel n’est activé ici.

L’espace client propose le planning CheckupAuto pour une nouvelle réservation et un lien séparé pour consulter les rendez-vous Mercure. Les identités et historiques des deux services ne sont pas fusionnés par e-mail.

## Audit historique du 30 septembre 2026

Le planning `https://rdv.checkupauto.fr/` répond et reste le service public de réservation. Le nouveau site fonctionne en préproduction sur `https://stage.179.198.210.187.sslip.io`.

L'API publique `/api/customer/providers` de la préproduction indique que Google, Apple et Microsoft ne sont pas configurés. Les parcours et le formulaire d'administration existent ; une connexion réelle n'est pas validée tant que les identifiants des applications fournisseurs ne sont pas installés.

Le nouvel espace client comprend le profil particulier/professionnel, la cagnotte et le parrainage, le rattachement du portefeuille à l'application iOS, l'import/analyse des procès-verbaux et leur téléchargement/suppression. Ce constat concerne l’audit historique ; le lien de nouvelle réservation mène désormais au planning CheckupAuto. Les comptes et historiques Mercure ne sont pas fusionnés automatiquement par adresse e-mail.

## Connexions Google et Microsoft / Hotmail / Outlook

Chaque connexion utilise un état à usage unique, un nonce, PKCE et un cookie de navigateur `__Host-` propre à chaque état, Secure et HttpOnly. Le retour doit arriver sur l'origine qui a initié la connexion. Google/Microsoft utilisent SameSite=Lax ; Apple utilise SameSite=None pour son retour form_post. Les jetons sont vérifiés par signature, audience, émetteur et dates. Microsoft accepte les comptes personnels du tenant consommateur uniquement.

Ces connecteurs servent à l'identification. Ils ne demandent pas d'accès aux boîtes Gmail, Hotmail ou Outlook.

Créer ou utiliser les applications OAuth dans Google Cloud et Microsoft Entra. Microsoft doit autoriser les comptes Microsoft personnels ; les comptes professionnels Entra nécessitent une politique séparée. Enregistrer exactement les URI suivantes :

| Fournisseur | URI de préproduction |
|---|---|
| Google | `https://test.checkupauto.fr/auth/customer/google/callback` |
| Microsoft | `https://test.checkupauto.fr/auth/customer/microsoft/callback` |
| Apple | `https://test.checkupauto.fr/auth/customer/apple/callback` |

Installer les clientId/clientSecret via `/admin/customers.html`, protégé par la session administrateur, MFA et CSRF. Les secrets restent dans le fichier privé `customer/oidc.json`, mode 0600 ; ne jamais les ajouter à Git ni aux journaux. Apple exige un secret signé valide et son renouvellement.

Après configuration, vérifier séparément : consentement réel, retour au même navigateur, session, déconnexion, refus/annulation, et absence d'accès au compte avec un autre fournisseur partageant l'e-mail. Si le fournisseur n'émet pas une adresse e-mail utilisable, afficher un échec sans créer de compte incomplet.

## Application iOS et espace client

Une build signée avec `CHECKUPAUTO_ENVIRONMENT=preproduction` utilise désormais `https://test.checkupauto.fr` pour l’API, le compte client et le planning public `/?utm_source=app:ios#reservation`. Elle n’ouvre plus le laboratoire administrateur `/payment/test` depuis le bouton de réservation. La production reste sur `https://www.checkupauto.fr` ; modifier la cible de préproduction ne bascule ni le site public ni une build déjà installée.

L’espace client s’ouvre dans le navigateur intégré Safari (`SFSafariViewController`) et utilise les connecteurs web Google, Microsoft personnel/Hotmail et Apple. Il n’existe pas encore de connexion native distincte à ces trois fournisseurs. La configuration privée des fournisseurs et une validation réelle de chaque connexion restent nécessaires ; les clés APNs/App Store Connect ne sont pas des identifiants OAuth clients.

La séparation des données locales production/préproduction et le refus de réinscription automatique après désinscription sont conservés. Le contrôle CI de l’API réelle utilise lui aussi PlanetHoster. Ces changements source ne prouvent pas à eux seuls qu’une nouvelle build a été distribuée sur TestFlight.

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

Les tests de paiement actuels utilisent le simulateur ; ils ne valident pas encore un échange bancaire Payline réel. Les paiements réels restent désactivés. Le connecteur Payline direct est une capacité sandbox distincte. La nouvelle cible produit délègue le paiement à Mercure ; elle nécessite son activation et une interface documentée, sans recopier ses identifiants commerçant dans CheckupAuto.
