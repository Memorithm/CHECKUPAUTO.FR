# Option 2 — illustration lavis fixe

Décision utilisateur du 8 octobre 2026 : conserver l’image fixe et supprimer les boutons « Rejouer l’apparition » et « Image fixe ».

L’illustration approuvée et les trois fichiers WebP restent inchangés. Le tracé simplifié, la 3D, les contrôles de présentation et l’animation ne sont pas chargés. Le JavaScript dédié à l’apparition, ses événements, son observateur et ses règles CSS sont retirés, et non simplement masqués. Le texte d’état associé aux boutons est également retiré.

L’image reste complète et accessible avec ou sans JavaScript, quelle que soit la préférence de mouvement. Les dimensions, le srcset, les priorités de téléchargement, les empreintes d’image et les ancres sous le menu fixe sont conservés. Le formulaire de réservation et les comptes clients ne sont pas modifiés.

Validation : tests de fidélité des fichiers et de suppression des contrôles ; Chromium et WebKit vérifient une opacité de 1, aucun clip, aucune animation et aucun téléchargement 3D.

Publication : test.checkupauto.fr seulement, via RemoteOps après CI verte au SHA exact. La production reste inchangée. Lien de contrôle : https://test.checkupauto.fr/#lavisHero
