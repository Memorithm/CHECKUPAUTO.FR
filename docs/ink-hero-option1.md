# Option 1 — illustration animée à l’encre de Chine

Statut : **démonstration pour avis du client, sur `test.checkupauto.fr` uniquement**. Le site de production reste inchangé jusqu’à une décision distincte.

## Changement visible

Le bandeau d’accueil conserve son texte, ses tarifs configurables, son offre « contre-visite offerte », sa navigation, son bouton de réservation et le parcours Mercure existant. La vue 3D WebGL de la voiture est remplacée par une illustration vectorielle intégrée au HTML, avec traits noirs et verts rappelant un pinceau à encre. Le contour, les vitres, la carrosserie, les roues et un trait de sol se dessinent progressivement en environ 3 secondes.

Un bouton « ↻ Rejouer le dessin » permet de relancer l’animation. Sur mobile, si la voiture n’est pas encore visible, un `IntersectionObserver` déclenche le dessin lorsque la voiture approche de l’écran ; il se déconnecte aussitôt. Le navigateur exécute seul les transitions CSS ; aucun boucle JavaScript ou moteur de rendu 3D ne fonctionne. Les visiteurs qui préfèrent une réduction des animations voient immédiatement un dessin **entier et immobile**. Si le JavaScript est désactivé, le SVG reste affiché.

## Ressources et confinement

- **0 requête GLB et 0 requête pour la photographie de secours** depuis cette page ; le GLB historique reste dans Git temporairement pour permettre un retour arrière tant que les options 1, 2 et 3 sont comparées.
- Aucun CDN, bibliothèque d’animation, polices tierces, service worker, données d’identification, nouveau service résident ou composant GPU.
- Le SVG est intégré dans le document HTML ; seules les feuilles CSS et le JavaScript de la page existants portent une révision d’URL pour éviter un ancien cache navigateur.
- Aucun changement de cache du compte client, des disponibilités, des paiements, du backend ou de Mercure.

## Conditions de validation

1. Tests unitaires : SVG autonome valide, absence d’import WebGL, accessibilité, `prefers-reduced-motion`, navigation et formulaire de réservation inchangés.
2. Sur Chromium et WebKit, vérifier écran 320–1920 px, stabilité de la géométrie, dessin progressif, arrêt, replay, mode réduit, absence de chargement GLB et chargement des créneaux.
3. CI entièrement verte au SHA exact avant fusion.
4. Déploiement de la seule préproduction **par RemoteOps**, avec vérification du SHA déployé et tests HTTP en lecture seule.
5. Après approbation esthétique, envisager le retrait des fichiers 3D historiques de la distribution. Ne pas publier la démo en production avant accord.

Lien de prévisualisation, après déploiement : https://test.checkupauto.fr/#inkCarStage (défile directement vers l’animation).
