# Accueil premium — illustration lavis fixe

Date : 8 octobre 2026. Cible de validation : `test.checkupauto.fr`, sans bascule du domaine de production.

## Choix retenus

L’illustration actuellement approuvée est conservée, octet pour octet, dans les trois WebP du manifeste `assets/illustrations/lavis-option2-manifest.json`. Aucun nouveau dessin, découpage, recoloriage, effet de filtre, masquage ou animation n’est appliqué à cette image. Le ratio et l’affichage `object-fit: contain` restent explicites.

Le titre passe à une typographie à empattements disponible sur le système, sans téléchargement de police. Le blanc et le vert sauge remplacent les grands aplats contrastés autour de l’image. Les boutons restent nettement identifiables, avec des cibles tactiles et le focus clavier existants. Le bloc principal est plus court sur ordinateur. Sur téléphone, le titre précède l’image, puis viennent la description et les actions : l’illustration n’attend plus la fin d’un long bloc de texte pour apparaître.

Les mentions « OPTION 02 · LAVIS », la description de démonstration et le deuxième cartouche d’offre ont été retirés du HTML. Le bandeau commercial existant est conservé en dessous de l’illustration, avec son texte configurable intact. Les tarifs, les offres, les liens de réservation, les comptes, le formulaire de contact et le paiement ne sont pas modifiés.

Les sections inférieures reprennent les mêmes caractères, marges, bordures et arrondis. Les modifications CSS sont limitées au corps `premium-home`, propre à l’accueil. Elles ne changent pas la mise en page de l’espace client ni celle des pages de paiement. Le JavaScript et les images de production n’ont pas changé.

## Vérification

- Tests de source pour l’image et ses empreintes, l’absence de commandes et d’étiquettes de démonstration, les liens métier, l’ordre du contenu mobile et l’absence de nouvelle dépendance.
- Tests Chromium et WebKit : dix tailles d’écran, géométrie de l’ensemble du parcours, apparition de l’image sans animation, ordre titre/image/description, navigation mobile, choix de prestation, sélection de créneau et formulaire client.
- Captures réalisées à partir du vrai code avec des réponses réseau fictives et isolées, puis contrôles en lecture seule sur l’URL de test après déploiement.
- Fusion seulement après CI verte sur la révision exacte. Déploiement par `Memorithm/RemoteOps`, avec vérification publique du SHA servi et des ressources.

## Retour arrière

Revenir à la version précédente validée par le contrôleur RemoteOps. Aucun changement de base de données ni de migration n’est associé à cette présentation. Les images originales restent inchangées et disponibles.
