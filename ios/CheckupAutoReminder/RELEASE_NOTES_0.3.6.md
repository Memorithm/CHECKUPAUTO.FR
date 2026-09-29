# Checkup Auto 0.3.6 (9)

- Scène développée de 102 points, sur toute la largeur disponible, avec marges horizontales réduites à 8 points.
- Voiture vectorielle plus grande, roues à rayons qui tournent et vraie remorque attelée portant « Votre CT arrive à échéance ».
- Le convoi entre par la droite, roule vers la gauche, ralentit et reste arrêté devant un petit centre « CONTRÔLE TECHNIQUE » ; le mouvement dure environ dix secondes et ne repart pas en arrière.
- Le test local utilise le mode transitoire d’ActivityKit : la Dynamic Island s’ouvre en grand automatiquement tant que l’app reste visible. Fermer la présentation ou quitter l’app termine la démo. Les vrais rappels conservent le mode standard.
- Réduire les animations et la luminance Always-On affichent le convoi déjà garé, avec son message lisible.
- Route de vérification visuelle réservée aux builds Debug pour enregistrer la scène native et la présentation système sur simulateur.
