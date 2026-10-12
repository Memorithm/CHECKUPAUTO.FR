# Paiements CheckupAuto — PayPal direct et Payline / Monext

État : transport Payline/Monext implémenté en homologation ; production codée derrière un double verrou (voir « Production Payline »).
Mise à jour : 24 septembre 2026.

## Plateforme bancaire identifiée : Payline / Monext, pas Monetico

La fiche de raccordement fournie par le commerçant indique explicitement **Payline Monext** et la devise EUR. Le fournisseur bancaire à intégrer pour ce contrat est donc Payline / Monext. Le nom de la banque acquéreuse ne permet pas de déduire le protocole technique à employer.

L'adaptateur Monetico de la première tranche reste une bibliothèque sandbox distincte, **non sélectionnée pour ce contrat**. Ce n'est pas un adaptateur Payline. Il ne faut ni lui injecter les références de cette fiche, ni réutiliser son MAC ou son format de notification comme s'ils étaient compatibles avec Payline.

La fiche originale, son image, le SIRET et ses références TPE/BIN/NLSA/3DS ne sont pas copiés dans le dépôt. Les fixtures de tests sont entièrement synthétiques. Le présent document en conserve seulement la conclusion technique utile.

La fiche distingue un TPE libellé « Merchant Id » et un identifiant Mastercard. Elle ne suffit pas à établir la correspondance avec le **merchantId API Payline**, ni le **contractNumber** configuré dans le compte Payline. Ces correspondances doivent être vérifiées auprès du centre d'administration ou du support, pas devinées à partir des libellés ou du format des chiffres. Elle ne contient pas d'Access Key API explicitement identifiée, et ne prouve pas l'activation des services API, du compte d'homologation, d'Apple Pay, de PayPal via Payline ou d'un mode d'encaissement donné.

## Périmètre effectivement codé

### Socle et connecteurs antérieurs

`payment_core.py` fournit les montants en centimes entiers, les intentions et un journal SQLite privé. La création est idempotente par réservation ; une modification incohérente de prestataire, montant ou empreinte de CGV est refusée. Les références prestataires sont uniques et immuables, les événements répétés dédupliqués, les états autorisé et capturé distincts.

`payment_paypal.py` contient le client sandbox OAuth / Orders v2, le contrôle des URL d'approbation, la capture avec identifiant d'idempotence et la validation ordre/marchand/référence/devise/montant. La vérification d'un webhook est suivie d'une relecture authentifiée de l'ordre. Les réponses sont minimisées ; les certificats transmis dans les notifications ne sont pas téléchargés par notre serveur.

`payment_monetico.py` reste le connecteur de test Monetico précédemment développé. Sa présence ne sélectionne aucune banque et ne valide pas le contrat Payline. Le socle `Intent` / `SandboxJournal` n'accepte encore que les fournisseurs `paypal` et `monetico` : l'ajout de Payline et la migration de son schéma ne sont **pas** réalisés par la présente tranche. Ne pas renommer un fournisseur existant dans une base ni réinterpréter ses anciens événements.

La PR #222 a ajouté 43 tests de paiement et sa CI a exécuté 985 tests avec succès. C'est une preuve historique de cette tranche, pas le nombre garanti de la suite courante. Aucun échange bancaire authentifié n'avait été effectué.

### Configuration Payline nouvellement préparée

`payment_payline_config.py` fournit :

- une configuration explicite avec `environment`, `merchantId`, `accessKey`, `contractNumber` et `publicOrigin` ;
- le refus des champs inconnus, des alias de la fiche acquéreur, des valeurs mal formées et des environnements autres que `sandbox` ;
- la conservation des identifiants comme chaînes, y compris leurs zéros initiaux ;
- un endpoint WebPayment fixé à l'homologation, non fourni par le navigateur ;
- la préparation de l'authentification HTTP Basic attendue, uniquement pour un futur transport TLS ;
- un compte rendu local qui n'expose aucun identifiant ni secret et conserve tous les indicateurs opérationnels à false.

Les limites de longueur et de caractères sont des politiques d'entrée bornées du projet, pas une attestation de validité du compte. `configurationSyntaxValid=true` ne signifie jamais que le secret fonctionne ou que le contrat est actif. Le code ne peut pas détecter qu'un opérateur a manuellement recopié une mauvaise valeur dans un champ correctement nommé : la vérification fournisseur reste indispensable.

Le module ne lit aucun coffre, aucune variable d'environnement et aucune fiche bancaire. Il ne contacte pas Monext, n'implémente pas encore doWebPayment/getWebPaymentDetails et n'est pas raccordé aux routes HTTP, au journal ou au back-office. Aucun statut « paiement autorisé », « capturé » ou « remboursé » ne peut provenir de ce simple préflight.

Les en-têtes retournés par `authentication_headers()` contiennent un secret encodé : **ne jamais les journaliser, les envoyer au navigateur ou les sauvegarder dans Git**. Base64 n'est pas un chiffrement. `repr(config)` masque les valeurs, mais ce masquage ne remplace pas la protection des objets en mémoire ni un coffre adapté.

Quatorze nouveaux tests locaux ont réussi sur Python 3.13 : séparation des champs API et acquéreur, refus du réel, conservation des zéros, authentification correcte, origine HTTPS, masquage des valeurs et absence d'effet réseau. Ils n'utilisent aucun paramètre réel du commerçant.

## Transport Payline sandbox implémenté le 24 septembre 2026

`payment_payline.py` implémente maintenant le transport SOAP WebPayment **homologation uniquement**. Il utilise l'endpoint fixe `https://homologation.payline.com/V4/services/WebPaymentAPI`, l'authentification HTTP Basic préparée par la configuration privée et la version API Payline 34.

Le parcours codé couvre `doWebPayment` avec paiement comptant action 101, page hébergée Payline, puis `getWebPaymentDetails`. Le navigateur n'est jamais une source de vérité : le résultat n'est transformé en `VerifiedEvent` qu'après relecture authentifiée côté serveur et contrôle du token, du montant en centimes, de la devise EUR (978) et de la référence de commande CheckupAuto. Les codes de résultat sont bornés : succès `00000`, refus identifiés et état explicitement en attente ; un code technique ou inconnu n'est pas converti en réussite.

Le journal sandbox accepte désormais le fournisseur `payline`. Une migration conservatrice reconstruit l'ancienne contrainte SQLite `paypal/monetico` sans réinterpréter les intentions ni les événements historiques. Les événements Payline sont idempotents comme les autres connecteurs.

Le parseur XML refuse les réponses surdimensionnées, DTD/ENTITY et ambiguïtés de champs critiques. Les redirections de sandbox sont limitées aux hôtes Payline d'homologation. Les identifiants API et l'Access Key ne sont jamais placés dans la trame métier ni dans les erreurs.

Ce transport ne signifie toujours pas que le compte marchand est authentifié ou que le contrat est actif. `checkoutBound=false`, `httpCallbacksBound=false`, `refundsBound=false` et `livePaymentsEnabled=false` restent fermés tant que nous n'avons pas les paramètres de l'environnement d'homologation, la recette fournisseur et la liaison sûre à la réservation.

### Configuration privée du connecteur

`payment_payline_private.py` charge maintenant la configuration sandbox exclusivement depuis un fichier privé hors du dépôt, par défaut `CYBERCHECK_PRIVATE_DIR/payments/payline-sandbox.json` ou via `CYBERCHECK_PAYLINE_CONFIG_PATH`. Le fichier doit appartenir à l'utilisateur du service, être régulier, non symbolique et sans droits groupe/autres. Le serveur ne crée ni ne modifie ce secret.

Le back-office Paiements reçoit uniquement un état minimisé : configuration présente/valide, transport disponible et portes opérationnelles. Aucun `merchantId`, `accessKey`, `contractNumber` ou origine privée n'est renvoyé au navigateur. Tant que l'authentification réelle auprès de Monext et le rattachement du contrat n'ont pas été vérifiés, les indicateurs correspondants restent faux.

### Retours navigateur et notification Payline

Les routes sandbox sont maintenant liées à l'application :

- `/payment/payline/return?paymentId=…` pour le retour du navigateur ;
- `/payment/payline/cancel?paymentId=…` pour une interruption utilisateur ;
- `/api/payments/payline/notify?notificationType=webtrs&token=…` pour le signal serveur Payline.

Le `paymentId` est un identifiant aléatoire CheckupAuto ; il sert uniquement à retrouver l'intention déjà créée. Aucun paramètre de résultat venant du navigateur n'est accepté. Le retour et la notification relisent l'état auprès de Payline avec `getWebPaymentDetails`, puis appliquent seulement l'événement vérifié au journal idempotent. La route d'annulation ne modifie jamais l'état du paiement sur la seule foi du navigateur.

Les réponses navigateur sont `noindex` et n'exposent ni token Payline, ni identifiant marchand, ni corps prestataire. Une configuration privée absente ou une relecture fournisseur indisponible laisse le paiement non confirmé et retourne un état temporairement indisponible plutôt qu'un faux succès.

### Devis de paiement lié à la réservation autoritaire

`payment_checkout.py` établit maintenant la frontière entre Mercure et le domaine paiement. Une intention sandbox ne peut être créée qu'à partir d'une réservation Mercure autoritaire déjà en état `confirmed` ou `completed`, jamais depuis le placeholder de confirmation navigateur.

Le service et le montant sont relus dans `booking_conversions`. Le navigateur ne fournit ni prix ni type de prestation au domaine paiement. Les deux seules familles payables restent le contrôle technique, plafonné à 80 €, et le véhicule aménagé/VASP, plafonné à 90 € ; un montant autoritaire inférieur reste possible pour un tarif promotionnel effectivement remonté par Mercure.

La création exige également une preuve finale d'acceptation des CGV associée à la référence de réservation autoritaire. Le `content_hash` de cette preuve devient le `terms_hash` du devis paiement. La référence Mercure brute n'est pas persistée dans le journal paiement : elle est transformée en une référence opaque dérivée.

Cette tranche crée seulement une intention interne sandbox et ne contacte pas Payline. Les portes `providerStartBound`, `publicStartRouteBound` et `livePaymentsEnabled` restent donc fermées. Cette séparation évite qu'un prix, un service ou une acceptation de CGV envoyés par le navigateur deviennent une autorité de paiement.

## Démarrage checkout sandbox raccordé le 24 septembre 2026

Le parcours serveur comprend désormais `POST /api/payments/payline/start`. Cette route n'accepte **ni montant, ni prestation, ni référence Mercure brute**. Le navigateur fournit uniquement son couple `ccid` / `cct` déjà signé par CheckupAuto ; le serveur retrouve la conversion Mercure autoritaire, relit le prix et la preuve de CGV, crée l'intention interne puis appelle `doWebPayment`.

Le démarrage est idempotent après une réponse fournisseur confirmée : le même rendez-vous restitue la même URL hébergée Payline sans créer un nouvel appel. Si l'appel réseau est ambigu (timeout ou rupture après envoi), l'intention passe dans un état de démarrage `indeterminate` et **aucune relance automatique vers Payline n'est effectuée**. Une réconciliation explicite est alors requise, afin d'éviter deux sessions bancaires concurrentes.

Le checkout reste strictement en environnement d'homologation. Une configuration privée Payline absente retourne un échec fermé et n'empoisonne pas l'intention pour une tentative ultérieure après configuration. `livePaymentsEnabled=false` demeure inchangé.

## Production Payline (12 octobre 2026)

La production est codée mais **fermée par défaut**. Elle ne s'ouvre que si deux verrous indépendants sont réunis :

1. **Fichier privé de production** : `$CYBERCHECK_PRIVATE_DIR/payments/payline-production.json`, ou le chemin donné par `CYBERCHECK_PAYLINE_PRODUCTION_CONFIG_PATH`. Le fichier appartient à l'utilisateur du service, avec les droits `600`. Il contient les mêmes cinq champs que le fichier de test, avec `"environment": "production"` et le `merchantId`, l'`accessKey` et le `contractNumber` **de production**.
2. **Interrupteur** : `CHECKUPAUTO_PAYLINE_LIVE_ENABLED=true`, exactement cette valeur.

Une fois les deux verrous réunis :

- **Nouveaux paiements.** Ils sont créés en environnement `production`. Les appels SOAP partent vers `https://services.payline.com/V4/services/WebPaymentAPI`. Seules les pages hébergées `webpayment.payline.com` et `payment.payline.com` sont acceptées pour la redirection.
- **Paiements existants.** Chaque intention garde son environnement d'origine. Un retour ou une notification relit toujours le paiement avec la configuration de **cet** environnement, jamais avec l'autre.
- **Fichiers non interchangeables.** Un fichier de test qui déclare `production`, ou l'inverse, est refusé (`payline_private_environment_mismatch`).
- **Pas de changement d'environnement pour un même rendez-vous.** Si un rendez-vous a déjà un paiement en homologation, aucun paiement de production ne peut lui être créé (`booking_payment_conflict`).
- **Remboursements.** Aucun remboursement n'est exposé sur le site (`refundsBound=false`).
- **Montants.** Ils restent bornés de 1 à 9 000 centimes. Une prestation de test à 0,01 € est donc possible, une fois rattachée côté Mercure.

**Retour arrière** : retirer `CHECKUPAUTO_PAYLINE_LIVE_ENABLED`. Les nouveaux paiements repartent alors en homologation, sans redéploiement. Les intentions de production déjà créées ne peuvent plus être relues tant que l'interrupteur est fermé. Leurs retours renvoient « vérification indisponible », jamais un faux succès.

Le journal `payments.sqlite3` existant est migré automatiquement au démarrage : la contrainte passe de `sandbox` seul à `sandbox` ou `production`, sans réécrire l'historique.

## Procédure de demande concernant un remboursement

Checkup Auto ne propose **aucun remboursement automatique** depuis le site, le checkout ou le back-office. Aucune route opérateur ne doit pouvoir appeler `doRefundRequest` et aucun bouton de remboursement n'est exposé.

Une demande concernant un remboursement passe exclusivement par le formulaire public `/contact`. Elle crée une demande de contact destinée à un traitement manuel séparé. La soumission du formulaire ne modifie jamais un paiement, n'appelle jamais Payline / Monext et ne vaut pas confirmation d'un remboursement.

Le transport Payline d'homologation préparé dans le code bas niveau reste non raccordé au produit : `refundsBound=false`. Il ne doit pas être considéré comme une fonctionnalité disponible ni être exposé sans décision produit explicite ultérieure.

## Accès à préparer avec Monext

Les données à obtenir depuis le **compte marchand Payline**, séparément pour les tests, sont :

| Paramètre | Origine / rôle |
| --- | --- |
| `merchantId` | Identifiant du compte commerçant API Payline, à confirmer dans le centre d'administration. |
| `accessKey` | Secret d'API de cet environnement ; à déposer exclusivement dans un coffre privé. |
| `contractNumber` | Contrat du moyen de paiement configuré et rattaché à ce compte. |
| Environnement | Compte d'homologation et contrat de test disponibles ; ne pas supposer que des références de production fonctionnent en test. |
| Origine HTTPS | Instance applicative capable de traiter les retours et notifications ; la démonstration HTML seule ne remplit pas ce rôle. |

Les codes banque, BIN, NLSA, ERT et références d'authentification carte sont à conserver pour le raccordement par les acteurs concernés. Leur présence ne remplace pas les trois paramètres API ci-dessus et ne doit pas conduire à inventer leur correspondance.

La première question opérationnelle est l'accès au centre d'administration Payline / Monext et à son environnement d'homologation. Aucune clé, aucun mot de passe ni numéro de carte ne doit être demandé dans une conversation. Ne pas régénérer un secret de production déjà utilisé sans inventorier ses consommateurs et préparer leur rotation.

## Parcours Payline à implémenter

La cible est une page de paiement hébergée par le prestataire, sans collecte du PAN/CVV sur CheckupAuto. Les droits précis et le kit courant du compte doivent encore être confirmés.

1. Établir côté serveur la réservation, son prix réellement applicable et une preuve d'acceptation des CGV.
2. Créer l'intention persistante et appeler **doWebPayment** avec les paramètres du compte d'homologation.
3. Conserver la liaison de l'intention au token émis par Payline avant la redirection du client.
4. Au retour navigateur **ou** à réception d'une notification, demander **getWebPaymentDetails** avec ce token. La notification n'est qu'un signal de relecture : aucun statut ni montant fourni par le navigateur ou le callback n'est accepté comme preuve de paiement.
5. Vérifier l'identité du contrat, la référence de commande, le montant, la devise, le résultat et la nature autorisation/capture avant une transition durable et idempotente.
6. Rapprocher paiement et réservation, traiter les réponses perdues et les compensations, puis confirmer au client une seule fois.

La documentation Monext précise qu'un résultat final doit être récupéré dès le retour du client, sans attendre une notification. Cette dernière sert aussi au cas où le client ne revient pas. Les deux chemins doivent converger vers le même traitement idempotent.

PayPal direct reste un canal séparé. PayPal proposé par Payline, Apple Pay ou un paiement fractionné ne sont pas activés par déduction à partir de la fiche bancaire. Une même commande ne doit jamais déclencher deux encaissements concurrents auprès de prestataires différents.

## Frontières de confiance et limites communes

`Quote` est une valeur interne : elle ne prouve ni l'identité du payeur, ni l'existence du créneau, ni le consentement. Le futur adaptateur doit vérifier la réservation et son tarif côté serveur. Un montant, une remise ou une empreinte de CGV fournis par le navigateur ne sont jamais suffisants.

Les catégories actuellement représentées sont `technical` jusqu'à 8000 centimes et `fitted` jusqu'à 9000. Ces plafonds permettent les remises autorisées mais n'en prouvent pas la légitimité. Les autres prestations restent hors du parcours en ligne.

`VerifiedEvent` est une valeur interne, pas une preuve cryptographique inviolable. Seul un vérificateur prestataire peut en produire un pour `_apply_verified`. Aucun JSON public ne doit être converti directement en cet objet. Un retour navigateur n'est jamais une preuve de règlement.

Les bases, journaux et clés demeurent hors racine Web. Ne pas enregistrer les réponses complètes, le contexte de facturation, les données carte ou les en-têtes d'autorisation dans les traces. Les références et empreintes ne sont pas qualifiées d'anonymes : conservation et droits RGPD restent à raccorder.

Une autorisation n'est pas une capture ; une capture n'est pas une preuve de règlement bancaire définitif ni d'absence de litige. Remboursements, réversions, contestations et rapprochement restent nécessaires avant exploitation réelle.

`booking_bridge.py` transfère encore le client vers Mercure après acceptation locale des CGV. Aucun maintien atomique du créneau pendant un paiement n'est prouvé. Une capture suivie d'une réservation impossible nécessite une compensation vérifiée, jamais une réussite fictive. Le choix entre paiement intégral, acompte et règlement au centre reste une décision métier à valider.

## Feuille de route et critères de sortie

1. **Compte Payline et contrat.** Confirmer accès, environnement, identifiant API, rattachement du contrat et droits d'encaissement. Ne pas utiliser la fiche comme credential.
2. **Transport Payline sandbox.** Implémenter le protocole documenté, bornes des corps/temps, TLS, erreurs minimisées, contrôle des redirections et lecture authentifiée des résultats. Ajouter le fournisseur au journal avec migration testée sans altérer les données PayPal/Monetico existantes.
3. **Liaison Mercure/prix/CGV.** Prouver le devis, la remise, le créneau et l'acceptation, couvrir expiration et échec de réservation. Définir les compensations avant toute offre publique d'encaissement.
4. **Reprises persistantes et routes sandbox.** Traiter les pannes entre appel réseau et écriture locale, doubles clics, notifications répétées/retardées/perdues. Pour PayPal, ne pas supposer que PayPal-Request-ID offre une idempotence illimitée. Sessions, CSRF, droits d'accès, limites de débit et boîte de réception durable doivent précéder l'exposition.
5. **Annulations et rapprochement.** Gérer les annulations, réversions, litiges et le rapprochement périodique sans exposer d'opération de remboursement. Toute demande client concernant un remboursement reste une procédure de contact manuelle distincte.
6. **Back-office Paiements.** Séparer configuration test/production, ne jamais renvoyer un secret, afficher transactions et anomalies minimisées ; ne pas exposer de commande de remboursement ; intégrer export comptable et conservation/droits RGPD.
7. **Recette puis production distincte.** Effectuer des échanges authentifiés de test avec les comptes dédiés, rapprocher le résultat du centre d'administration, tester interruption et restauration, puis obtenir la validation du commerçant avant le réel. Aucun test simulé ne remplace cette recette.

Aucun de ces éléments ne modifie le T430, OwnCloud, la démonstration, ses tunnels ou les blocages de contractualisation publique existants.

## Références primaires

Monext, documentation consultée le 22 septembre 2026 :

- API Key, authentification HTTP Basic par merchantId/accessKey : https://api-docs.retail.monext.com/docs/api-key
- Intégration pas à pas, compte d'homologation et distinction merchantID/merchantAccesskey/contractNumber : https://docs.monext.fr/spaces/DT/pages/747146908
- Endpoints SOAP et homologation WebPayment : https://docs.monext.fr/spaces/DT/pages/747146806
- doWebPaymentRequest, page mise à jour le 16 mai 2025 : https://docs.monext.fr/spaces/DT/pages/747145165
- getWebPaymentDetailsResponse : https://docs.monext.fr/spaces/DT/pages/747145170
- Notification par URL, page mise à jour le 5 juillet 2024 : https://docs.payline.com/spaces/DT/pages/747147276

Les mentions SSL V3 présentes dans certaines anciennes pages ne constituent pas notre politique TLS : la future connexion HTTPS doit employer une pile TLS maintenue avec vérification de certificat, sans dégradation vers SSL obsolète.

PayPal, références de l'adaptateur antérieur :
https://developer.paypal.com/api/orders/v2/orders-create
https://developer.paypal.com/api/orders/v2/orders-capture
https://developer.paypal.com/api/rest/webhooks/rest/

Monetico, référence historique de l'adaptateur non sélectionné pour ce contrat (Euro-Information v2.0, février 2025, version filaire 3.0) :
https://www.monetico-paiement.fr/fr/info/documentations/Monetico_Paiement_documentation_technique_v2.0.pdf

## Validation développeur

Aucune clé n'est nécessaire :

```bash
python3 -m unittest -v payment_payline_config_test payment_connectors_test
python3 -m compileall -q payment_payline_config.py payment_core.py payment_paypal.py payment_monetico.py
```

La Security CI découvre tous les fichiers `*_test.py`. Son résultat doit être vérifié au SHA de la PR puis après fusion. Les indicateurs du module Payline restent fermés même lorsque tous ces tests passent.
