# Checkup Auto iOS 0.2.0 (build 2)

## Tableau de bord
- Nouvelle interface SwiftUI claire et premium, cohérente avec le site Checkup Auto.
- Prochaine échéance de contrôle technique mise en avant.
- Synthèse de l’état push/local et du rattachement Mercure.
- Cartes d’accès rapide vers réservation, espace client et analyse du rapport CT.
- Les parcours web sont présentés dans un navigateur système sécurisé intégré à l’app pour préserver cookies et authentification.

## Fidélité
- Affichage natif de la cagnotte serveur déjà rattachée à l’iPhone.
- Nouveau rattachement à usage unique depuis le compte web vers l’app iOS ; aucune seconde cagnotte n’est créée.
- Solde acquis, montant en attente, code de parrainage et activité visible sans recalcul local.
- La source de vérité reste le moteur central Checkup Auto.

## Rapports de contrôle technique
- Accès direct depuis l’app au scanner du tableau de bord client.
- Le backend accepte PDF, JPEG et PNG, extrait le texte, structure les défauts, chiffre les données conservées et produit une représentation Markdown.
- Le conseiller préventif explique les défauts sans modifier la gravité réglementaire du procès-verbal.

## Véhicules
- Refonte de l’ajout manuel d’un véhicule.
- Affichage distinct des véhicules locaux et des véhicules rattachés au centre.
- Suppression locale explicite avec confirmation.

## Compte client
- Accès à l’espace client particulier/pro depuis l’app.
- Destinations du compte et du scan CT fournies par le bootstrap serveur avec repli compatible sur les anciennes versions du staging.

## Sécurité et confidentialité
- Aucun mot de passe Checkup Auto ajouté à l’app.
- Aucune duplication de la cagnotte côté iPhone.
- Les rapports CT restent gérés par le compte authentifié ; l’app ne contourne pas l’identité web.
