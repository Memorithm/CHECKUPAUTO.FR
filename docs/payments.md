# Paiements CheckupAuto — PayPal et VAD Crédit Mutuel

État de cette tranche : fondation technique sandbox, non raccordée au checkout.
Date de recherche et de validation locale : 22 septembre 2026.

## Périmètre effectivement codé

`payment_core.py` fournit les valeurs monétaires en centimes entiers, les intentions de paiement et un journal SQLite privé explicitement fourni par l'appelant. La création est idempotente par réservation ; changer le prestataire, le montant ou l'empreinte des CGV pour cette même réservation est refusé. Une référence prestataire ne peut pas être réaffectée. Les notifications répétées sont dédupliquées de façon persistante. Une autorisation ne devient jamais une capture par simple changement de libellé.

`payment_paypal.py` fournit un client OAuth et Orders v2 limité à `api-m.sandbox.paypal.com`. Il prépare une commande, contrôle son URL d'approbation sandbox, effectue une capture avec un identifiant d'idempotence propre à l'opération et vérifie le marchand, l'ordre, la référence interne, la devise EUR, le montant et la capture complète. Une notification n'est acceptée qu'après vérification de sa signature par l'API PayPal et relecture authentifiée de l'ordre. Les certificats fournis dans les notifications ne sont pas téléchargés par notre serveur.

`payment_monetico.py` prépare un formulaire vers la page hébergée de test, signe tous les champs selon la méthode MAC documentée et vérifie les notifications serveur à serveur. Le code sandbox `payetest` est enregistré comme `authorized`, pas comme argent capturé ou crédité sur le compte bancaire. Les champs bruts du callback ne sont pas conservés dans le journal.

Les 43 tests de `payment_connectors_test.py` ont été exécutés localement. Ils utilisent exclusivement des identités synthétiques, un secret de test explicite et des transports PayPal simulés. Le vecteur MAC UTF-8 est également calculé indépendamment avec OpenSSL. Cette validation n'est PAS un échange réussi avec un compte PayPal ou un TPE Monetico.

La fonction `payment_core.capability()` expose des indicateurs fermés : `livePaymentsEnabled=false`, `checkoutBound=false`, `httpCallbacksBound=false`, `refundsBound=false`, `merchantSecretsConfigured=false`. Ils décrivent cette tranche, pas un diagnostic d'un coffre de production.

Aucun serveur, tunnel Cloudflare, port réseau, formulaire public, paiement réel, compte marchand ou configuration bancaire n'est créé ou modifié. La démonstration HTML sur le T430 demeure sans paiement réel.

## Offres bancaires à ne pas confondre

Le Crédit Mutuel présente Monetico Online Starter et Premium pour le paiement sur Internet. Sa grille commerciale de juin 2026 mentionne CB/Visa/Mastercard, Apple Pay et PayPal dans les deux formules, avec des modes d'encaissement plus étendus dans Premium. Les options disponibles restent celles du contrat réellement souscrit ; leur présence dans cette grille ne les active pas dans CheckupAuto.

PayPal direct et PayPal proposé dans Monetico sont deux intégrations possibles, pas deux encaissements à exécuter pour une commande. Le journal interdit pour l'instant le changement de prestataire d'une même intention ; une bascule après échec nécessitera une procédure explicite de rapprochement et de révocation.

Une option VAD sur un TPE physique ou une offre par lien de paiement n'établit pas automatiquement un contrat d'intégration Monetico compatible avec ce code. L'intitulé exact de l'offre, la caisse/fédération, l'environnement de test et les options contractuelles sont à confirmer. Aucune API Pay Pro n'est supposée ni inventée.

Source commerciale officielle, Crédit Mutuel, juin 2026 :
https://www.creditmutuel.fr/fr/professionnels/comptes/monetico-paiement.html
https://www.creditmutuel.fr/fr/professionnels/comptes/monetico-online-premium.html

## Références techniques et limite de validation

PayPal, documentation Orders v2 et webhooks consultée le 22 septembre 2026 :
https://developer.paypal.com/api/orders/v2/orders-create
https://developer.paypal.com/api/orders/v2/orders-capture
https://developer.paypal.com/api/rest/webhooks/rest/

Monetico : base de protocole vérifiée dans la documentation technique Euro-Information v2.0, février 2025, version filaire `3.0`, sections 1.4.2, 1.4.3, 9.3, 9.5 et 9.8 :
https://www.monetico-paiement.fr/fr/info/documentations/Monetico_Paiement_documentation_technique_v2.0.pdf

Le formulaire utilise la page complète hébergée, sans numéro de carte ni cryptogramme. Le contexte de facturation attendu est obligatoire ; aucun renseignement client manquant n'est inventé. La clé MAC est convertie depuis sa représentation hexadécimale en octets et couvre tous les champs, sauf MAC, triés par nom et encodés en UTF-8. Aucun repli vers l'ancien MAC positionnel n'est accepté.

Le kit actuel livré avec le contrat devra être comparé à cette base AVANT de déclarer l'intégration bancaire validée. Le téléchargement du kit courant n'a pas été validé dans cette tranche. Les pages officielles de distribution sont :
https://www.monetico.com/online/fr/espace-developpeur.html
https://www.monetico.com/online/fr/support-technique.html

## Frontières de confiance

`Quote` est une valeur INTERNE. Ses contrôles de type et son empreinte de CGV ne prouvent ni l'identité du payeur, ni l'existence du créneau, ni le consentement. Le futur adaptateur devra vérifier la réservation côté serveur, son prix réellement applicable et une acceptation enregistrée. Ne jamais construire Quote directement depuis un montant ou un hash fournis par le navigateur.

Les plages `technical` jusqu'à 8000 centimes et `fitted` jusqu'à 9000 permettent de représenter les réductions existantes. Elles n'autorisent pas une remise arbitraire : son montant devra être prouvé depuis le parcours tarifaire serveur/Mercure. Les autres catégories demeurent exclues.

`VerifiedEvent` est également une valeur INTERNE et non une attestation cryptographique inviolable. Seuls les vérificateurs prestataires peuvent en produire une pour appeler `_apply_verified`. Une route HTTP ne doit jamais convertir un JSON client en VerifiedEvent ni appeler directement `capture_evidence` sur ce JSON.

Une URL de retour navigateur ne constitue pas une preuve de règlement. Les futures pages de retour liront uniquement l'état serveur. L'URL de notification Monetico devra être enregistrée séparément auprès de la banque ; `url_retour_ok` ne la remplace pas.

Un `COMPLETED` PayPal accepté représente une capture selon l'API, pas une garantie d'absence de remboursement ou de contestation ultérieure. Les événements de remboursement, litige, réversion et règlement bancaire sont encore hors périmètre et doivent précéder l'exploitation réelle.

Le journal et les clés sont hors racine Web. Ne jamais journaliser les réponses prestataires complètes, les en-têtes d'autorisation, le formulaire bancaire et son contexte de facturation, ou les corps bruts des notifications. Les empreintes et références de paiement ne sont pas présentées comme des données anonymes : leur conservation et les droits applicables devront être intégrés aux moteurs RGPD existants.

## Parcours existant et chantier à raccorder

`booking_bridge.py` transmet encore l'utilisateur vers Mercure après le contrôle local des CGV. Cette tranche ne prouve pas de réservation atomique d'un créneau pendant un paiement. Il faut donc définir puis vérifier l'ordre exact des opérations avant de proposer l'encaissement.

Cible de travail : devis serveur et preuve de CGV → réservation ou maintien vérifié du créneau → intention persistée → prestataire choisi → confirmation serveur authentifiée → rapprochement paiement/réservation → confirmation client idempotente. Une capture suivie d'une réservation impossible nécessite une compensation, jamais une réussite fictive.

Le choix métier entre règlement intégral, acompte et paiement au centre n'est pas décidé par ce code. L'activation d'un règlement intégral de contrôle technique devra être explicitement validée. Le prépaiement d'un service n'est pas automatiquement la confirmation d'un rendez-vous Mercure.

## Feuille de route et critères de sortie

1. **Liaison réservation/prix/CGV.** Ajouter l'adaptateur de confiance sans modifier le prix depuis le navigateur ; couvrir créneau expiré, remise réelle, modification de CGV, échec Mercure et réservation préexistante. Documenter le maintien de créneau disponible ou son absence. Aucun encaissement public tant que le scénario de compensation n'est pas défini et testé.
2. **Exécution persistante et reprises.** Ajouter les opérations create/capture en cours, les délais, le rapprochement prestataire et les cas de panne entre appel réseau et écriture SQLite. La stabilité de PayPal-Request-ID n'est pas une garantie d'idempotence illimitée dans le temps. Ne jamais recréer silencieusement un ordre après une réponse perdue ou une fenêtre fournisseur expirée.
3. **Routes sandbox et expérience client.** Raccorder les sessions, CSRF, limites de débit et de taille, l'authentification des droits d'accès, les pages de retour et une origine HTTPS stable. Prévoir une boîte de réception durable des notifications et un traitement compatible avec les délais des prestataires ; la séquence de relecture PayPal n'est pas à exécuter sans limite dans une réponse HTTP synchrone. Un callback bancaire correctement signé mais incohérent avec la commande doit être isolé et rapproché, sans être déclaré payé ni confondu avec un MAC invalide. Le générateur d'accusé de réception seul n'est pas un récepteur HTTP achevé.
4. **Gestion des opérations.** Ajouter annulation, remboursement complet et partiel bornés par le total réellement capturé, réversions, litiges, rapprochement périodique et retour après panne. Confirmer les modes Monetico souscrits et la différence autorisation/capture/remise.
5. **Back-office Paiements.** Fournir configuration séparée test/production, état des connecteurs, listes et détail minimisés, liens de rapprochement, remboursement soumis aux droits administrateur/MFA et audit. Ne jamais renvoyer un secret enregistré au navigateur. Ajouter export comptable et intégration conservation/droits RGPD sans exposer le registre financier publiquement.
6. **Recette prestataires puis production.** Utiliser de vrais comptes sandbox dédiés, des événements issus de transactions sandbox et le kit du TPE souscrit. Vérifier les notifications répétées, retardées et perdues, les retours sans notification, le double clic, l'interruption réseau, la restauration du journal et les remboursements. Les événements du simulateur webhook PayPal ne remplacent pas une recette avec signature vérifiable. Activer le réel dans une tranche distincte seulement après ces preuves et validation du commerçant.

## Validation développeur

Aucun secret n'est requis pour ces tests :

```bash
python3 -m unittest -v payment_connectors_test
python3 -m compileall -q payment_core.py payment_paypal.py payment_monetico.py
```

La Security CI existante découvre `*_test.py` et exécute donc aussi ces tests. Les résultats de la CI et le SHA fusionné doivent être consultés dans la PR ; le nombre de tests local ne prouve pas le succès de toute la suite du dépôt.

## Préparation des accès — sans les communiquer dans une conversation

À préparer ensuite dans un coffre privé : pour PayPal, compte Business de test, application sandbox, identifiant marchand et identifiant de webhook ; pour Monetico, TPE/code société et clé du contrat de test. Les identifiants synthétiques des tests ne sont pas utilisables auprès des prestataires.

La première information à obtenir du commerçant est l'intitulé exact du contrat VAD et son état de souscription. Aucun mot de passe, aucune clé, aucun numéro de carte n'est nécessaire pour cette clarification.
