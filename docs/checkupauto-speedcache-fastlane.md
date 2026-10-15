# CheckupAuto SpeedCache / FastLane v1

## Profil confirmé dans le dépôt (15/10/2026)

- `index.html` utilise une illustration WebP responsive, **pas** le moteur 3D.
- `style.css` compte environ 61 Ko, `app.js` environ 24 Ko avant compression.
- L'hébergement LiteSpeed sert déjà le CSS, JS et les WebP publics avec un
  cache HTTP d'environ une semaine et Brotli sur CSS (constat historique du
  8 octobre, à revérifier sur une release active).
- `assets/public-asset-cache.js` conserve déjà le GLB public vérifié SHA256.
  Ne pas installer un cache WordPress sur ce site Python/Passenger.
- Le goulot structurel le plus coûteux peut être le premier passage par
  `passenger_wsgi._ensure_backend()`, qui importe le serveur et initialise
  plusieurs magasins SQLite. La lenteur réelle de `/compte` n'est pas encore
  mesurée, et FastLane **ne la corrige pas directement**.

## Lot 1 livré

1. `public_config_fastlane.py` sert uniquement un `GET /api/site-config`
   **anonyme, sans cookie, sans Authorization, sans query string** ; autres
   appels passent au serveur existant.
2. Snapshot JSON en mémoire **par worker**. La clé dépend du chemin, device,
   inode, taille, mtime nanoseconde et ctime : la prochaine requête détecte
   automatiquement une sauvegarde de configuration par `os.replace`.
   Pas de TTL arbitraire et aucune donnée obsolète conservée en cas d'erreur.
3. Limite stricte à 256 Kio ; lecture et vérification avant/après fichier ;
   aucune I/O réseau, nouveau composant SaaS, base de données ou service
   résident. Pas de nouveau point d'API ni réglage des sessions.
4. Les réponses restent `Cache-Control: no-store`. Les seuls marqueurs
   supplémentaires sont `X-CheckupAuto-FastLane: hit|miss` et
   `Server-Timing: fastlane;dur=<ms>` pour diagnostiquer la vitesse
   **serveur** de cette route ; ils ne transmettent aucune donnée personnelle.
5. Préchargement anticipé du WebP principal via `imagesrcset` et
   `imagesizes` identiques à l'image réellement affichée (évite un double
   téléchargement par changement de taille).

## Hors cache (obligatoire)

Aucune route `/compte`, `/api/customer/*`, `/api/booking/*`,
`/api/admin/*`, `/auth/*`, `/payment/*`, réservation Mercure, liste de
véhicules, session, profil ou paiement n'est incluse. Les appels portant
une session/cookie ou une Authorization sont toujours transmis au Handler
avec les contrôles d'accès originaux. Le mode migration-write-freeze garde
la priorité sur FastLane.

## Mesure avant / après et exploitation

Sur la même connexion, vérifier 10 à 30 requêtes anonymes indépendantes,
en cold/warm puis sur une configuration modifiée, avec les métriques TTFB,
`Server-Timing` et **p95**. Comparer à la version précédente à charge et
réseau équivalents. Ne pas inférer le gain sur `/compte` depuis
`/api/site-config`. Pour l'expérience utilisateur, utiliser Lighthouse
mobile + données de terrain CWV : LCP, INP, CLS et navigation vers
`/compte` à froid, puis à chaud. Ne jamais collecter identifiants,
cookies ni informations de réservations dans la télémétrie.

Cette optimisation prépare SpeedCache mais **ne remplace pas** les actions
plus structurantes : sessions conservées par le serveur d'identité,
démarrage à froid plus léger, réduction des charges CSS/JS et exposition
des bons en-têtes cache au niveau LiteSpeed pour les seuls médias publics.

Déploiement : PR verte, SHA immuable, RemoteOps, métriques sur
`test.checkupauto.fr` et rollback si régression. Aucune activation
automatique du cache HTML/service worker n'est autorisée.
