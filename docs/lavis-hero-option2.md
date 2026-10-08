# Option 2 — illustration lavis approuvée

Date : 8 octobre 2026. Prévisualisation : `https://test.checkupauto.fr/#lavisHero`.

Cette version remplace le SVG simplifié de l’option 1 par **les pixels de l’illustration de l’option 2 montrée dans la conversation**, et non par un nouveau dessin approximatif. La voiture, ses ombres, ses roues et ses coups de pinceau sont conservés. Les zones périphériques de la maquette contenant la navigation, le nom, l’adresse de compte, le libellé « particulier », le badge et le texte manuscrit ont été exclues avant publication. La maquette complète contenant les informations personnelles ne fait pas partie du dépôt ni des fichiers publics.

## Visuel et animation

Le visuel fixe reste la référence. Il est encodé en WebP à trois largeurs (765, 1020 et 1530 pixels), sans déformation, avec `srcset`, dimensions explicites et priorité de chargement élevée. Le fichier maître de 223 820 octets a l’empreinte SHA-256 `87dcf1d5fab5c07eb50d4cf7dcf3bc26854427ad8370ff7c459a9501aa2cf94f`. Les autres tailles pèsent 74 450 et 120 320 octets dans cette révision. Le manifeste permet de vérifier chaque fichier livré.

L’apparition décorative dure **2,6 secondes**, par transparence et dévoilement progressif CSS. Elle ne modifie pas les traits de l’illustration. Au terme de l’animation, sa classe est supprimée : l’image entière reste immobile. « Rejouer l’apparition » relance uniquement cet effet. « Image fixe » l’arrête immédiatement et affiche l’œuvre complète. La préférence de réduction des mouvements, y compris lorsqu’elle change pendant la visite, désactive l’effet. Sans JavaScript, le visuel reste directement visible et les commandes inactives sont masquées. Sur mobile, la première apparition attend que l’image soit visible.

Il n’y a aucun canvas, moteur WebGL, téléchargement GLB, vidéo ou lecteur Lottie sur la page. L’ancien code de parallaxe vidéo inutilisé a été retiré du JavaScript d’accueil. Une image décodée et les opérations CSS ont un coût mémoire réel ; cette implémentation ne prétend donc pas consommer « zéro mémoire ».

## Intégration

Seul le bandeau visuel d’accueil et ses contrôles changent. Textes commerciaux existants, tarifs, navigation, réservation, authentification, paiement et politiques de cache privées sont inchangés. L’ancienne ancre `#inkCarStage` reste compatible ; `#lavisHero` montre également le bandeau d’option et les boutons. Les deux ancres réservent la hauteur du menu fixe sur mobile et ordinateur.

Les styles et le JavaScript utilisent `lavis-option2-20261008-1` pour invalider leurs anciens caches. Les images sont servies par l’hébergement du site. Aucun service tiers n’est appelé pour afficher l’illustration. La prévisualisation autonome du dépôt inclut une liste blanche explicite de ces trois images et les embarque sans accès réseau.

## Vérifications et déploiement

Les tests vérifient l’empreinte de l’image approuvée, les budgets de poids, les dimensions, le texte alternatif, l’absence de données personnelles dans le HTML public, les contrôles de lecture/arrêt, la visibilité sans scripts, le mode réduit et l’absence de requêtes 3D. Les tests de géométrie et de réservation existants restent exécutés sur Chromium et WebKit.

Fusion uniquement après CI verte sur le SHA exact. Déploiement sur **test.checkupauto.fr uniquement**, via le contrôleur approuvé `Memorithm/RemoteOps`, puis vérification du SHA servi, des empreintes des trois fichiers et de l’affichage/relecture dans les navigateurs. La production ne doit pas être modifiée au titre de cette comparaison artistique.
