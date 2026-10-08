# Cache public léger — CHECKUPAUTO.FR

Date : 8 octobre 2026. Périmètre : site public, puis homologation sur test.checkupauto.fr.

## Constat mesuré avant la correction

- CSS, JavaScript et WebP publics : `Cache-Control: public, max-age=604800` observé sur le serveur LiteSpeed PlanetHoster ; Brotli est actif pour le CSS. Installer un cache WordPress ne correspond pas au code du site.
- Le modèle public `assets/3d/CyberCheckVehicle_Photo3D.glb` pèse 1 221 768 octets (environ 1,22 Mo) et n'avait pas de `Cache-Control` observable.
- La carte OpenStreetMap locale (84 560 octets) et le QR code, tous deux situés sous la ligne de flottaison, étaient chargés immédiatement.
- Les mesures ponctuelles de TTFB ont montré une forte variabilité entre les appels HTTP simples et les navigations instrumentées ; ne pas promettre un gain global en secondes sans tests comparables et métriques de terrain.

## Module et frontières de sécurité

1. `assets/public-asset-cache.js` : cache navigateur volontairement borné à **un seul fichier 3D public**, versionné par son empreinte SHA-256 complète. Stockage dans Cache Storage uniquement lorsque le navigateur l'autorise ; repli sur un téléchargement réseau vérifié si Cache Storage indisponible.
2. Aucun service worker, aucune dépendance externe, aucun CDN, aucun identifiant utilisateur, aucun cookie de compte transmis pour la ressource. La requête utilise `credentials: omit`. Le cache est strictement limité au modèle 3D sur la même origine, à un fichier vérifié par SHA-256, à une taille maximale de 4 Mio et à un MIME permis. Toute altération déclenche un nouveau téléchargement ou l'affichage du visuel de secours ; aucun contenu personnel n'est stocké.
3. `assets/3d/.htaccess` : politique HTTP LiteSpeed limitée aux fichiers GLB (`public, max-age=604800, stale-while-revalidate=86400`), sans modification du cache HTML, des formulaires, des API, de l'authentification ou des règlements. L'hébergeur doit confirmer effectivement la prise en charge via les en-têtes HTTP après déploiement.
4. Le modèle interactif est téléchargé après les premières images peintes, dans une plage d'inactivité du navigateur. Si l'utilisateur active `Save-Data`, conserver uniquement la photographie du véhicule pour éviter 1,22 Mo supplémentaires.
5. Image d'accueil prioritaire (`fetchpriority=high`). Carte et QR sous le premier écran différés (`loading=lazy`).

## Conditions de déploiement et rollback

- Publier sur **test.checkupauto.fr**, uniquement après réussite des tests et CI sur le SHA exact.
- Vérifier `/api/public/deployment-provenance`, les en-têtes du GLB, son SHA-256, le rechargement avec et sans Cache Storage, l'affichage 3D/fallback et les réservations sur navigateurs Chromium et WebKit.
- Ne pas mettre en cache `/api/`, `/compte`, `/contact`, `/go/booking`, `/payment`, ni les pages et JSON personnalisés.
- En cas de régression, revenir au SHA précédent via **RemoteOps**, sans manipuler les données clients.

## Sources techniques (consultées le 8 octobre 2026)

- Mozilla MDN, *Mise en cache HTTP* : https://developer.mozilla.org/fr/docs/Web/HTTP/Guides/Caching
- Mozilla MDN, *Cache-Control* : https://developer.mozilla.org/fr/docs/Web/HTTP/Reference/Headers/Cache-Control
- web.dev, *Optimiser le Largest Contentful Paint* : https://web.dev/articles/optimize-lcp?hl=fr
- LiteSpeed, *Cache settings and configuration contexts* : https://www.litespeedtech.com/docs/webserver/config/context/static

Le cache de modèles n'est ni un outil de suivi d'audience ni un mécanisme de profilage. La qualification juridique globale RGPD reste distincte de ces vérifications techniques.
