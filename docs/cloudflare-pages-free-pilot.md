# CheckupAuto — CDN public gratuit sans migration DNS (Cloudflare Pages Free)

## Choix prioritaire

Pour accélérer les ressources publiques et préserver le planning Mercure et
la messagerie, **Cloudflare Pages Free** est préférable pour le premier pilote.
Un sous-domaine personnalisé (ex. `static.checkupauto.fr`) peut être attaché
à Pages avec un **CNAME chez N0C**, sans changer les serveurs DNS autoritaires
du domaine ni l'enregistrement OVH.

La distribution mondiale de fichiers statiques sur Pages est gratuite (sans
Pages Functions), et Pages sert directement ETag/Brotli. Le plan Free prévoit
500 builds/mois, 20 000 fichiers/déploiement et 25 MiB/fichier. Le site
application, les API, l'authentification, les paiements et Mercure ne migrent pas.

## Implémentation

- `scripts/build_cloudflare_pages_public.py` génère
  `.cloudflare-pages-public/` avec une **liste blanche** d'images/CSS/JS/
  médias publics. L'export exclut admin, SQL, Python, secrets, configurations
  privées, les données clients et les fichiers Blender.
- Un `_headers` noindex est inclus pour ne pas indexer le CDN en tant que
  seconde version du site. Aucun Worker, Pages Function, cache HTML ou
  Service Worker n'est ajouté.
- `public_image_cdn.py` est un pilotage **OFF par défaut**. Il remplace
  uniquement les URLs des images du modèle HTML public lorsque
  `CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN=https://static.checkupauto.fr`.
  Les scripts et CSS restent volontairement à la même origine, afin de ne
  pas compromettre la Content Security Policy `script-src 'self'` ni les
  modules JS/imports relatifs.
- Aucune requête d'un compte, d'une session, d'un paiement ou d'un créneau
  Mercure ne passe par Pages. Aucun cookie utilisateur n'est transféré au
  CDN d'images.

## Activation une fois Cloudflare connecté

1. Ouvrir <https://dash.cloudflare.com/sign-up> et créer un compte Free,
   activer MFA. Ne pas configurer la délégation `checkupauto.fr` vers
   Cloudflare pour ce pilote Pages.
2. Dans **Workers & Pages → Create → Pages**, connecter le dépôt GitHub
   `Memorithm/CHECKUPAUTO.FR`. Sélectionner la branche de déploiement
   revue et **aucun preset framework**. Réglages :
   `Build command: python3 scripts/build_cloudflare_pages_public.py`;
   `Build output directory: .cloudflare-pages-public` ;
   `Root directory: /`.
3. Laisser Pages construire une première version
   `<nom-du-projet>.pages.dev`. Tester que les images et CSS publics y
   sont accessibles. Contrôler que `/admin/`, `/api/customer/me`,
   `/private/`, `/data/` et les scripts Python sont introuvables.
4. Dans le projet Pages, **Custom domains → Set up domain** :
   ajouter `static.checkupauto.fr` (association **avant** le CNAME).
   Chez N0C (zone DNS actuelle), créer le **seul** enregistrement
   `static CNAME <nom-du-projet>.pages.dev`. Ne pas remplacer les NS
   OVH/N0C ni les records MX, mail, rdv, ftp, apex/www.
5. Après activation HTTPS et tests de ressources sur ce sous-domaine,
   activer l'env de préproduction
   `CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN=https://static.checkupauto.fr`
   par le mécanisme de configuration **autorisé RemoteOps** (aucun secret
   dans GitHub). Redémarrer Passenger proprement. Sans cette variable,
   le comportement reste identique à la version précédente.
6. Vérifier sur iPhone/Safari le rendu de l'image principale et
   `imagesrcset`, absence de CORS/CSP errors et de double chargement
   image. Mesurer 30+ navigations froid/chaud, LCP/p95 TTFB, requêtes
   transférées depuis Pages vs PlanetHoster ; revalider Google/Apple,
   réservations Mercure et paiement test.
7. En cas de régression, **désactiver la variable** puis redémarrer
   Passenger ; aucune migration DNS ou changement de session à annuler.
   Les autres actifs restent servis par LiteSpeed comme auparavant.

## Pilote immédiat via `pages.dev` (15 octobre 2026)

Le déploiement Pages GitHub est effectif à **https://checkupauto-fr.pages.dev**.
Le manifeste public `/public-assets-manifest.json` est servi et contient
les fichiers attendus ; un contrôle HTTP indépendant vérifie WebP, CSS,
JavaScript et GLB (code HTTP, SHA256, absence de `Set-Cookie`) et le refus
des chemins privés. L'URL racine `/` répond 404 : c'est le comportement
attendu pour cette distribution de **ressources seulement**, pas une erreur.

Sur l'hôte **strictement exact** `test.checkupauto.fr`, la page d'accueil
anonyme utilise directement `https://checkupauto-fr.pages.dev` pour ses
images publiques `/assets/illustrations/`, `/assets/guides/`,
`/assets/premium/` et médias d'application autorisés. Aucun domaine
personnalisé ni enregistrement DNS n'est nécessaire pour commencer.
L'image `src`, ses variantes `srcset` et son `preload` utilisent la
même origine CDN. CSS et JS demeurent sur le site principal pour éviter
un changement CSP ou une incompatibilité des URLs relatives.

Les routes de connexion, les comptes, les véhicules, les paiements,
les API et Mercure **ne passent jamais par Pages**. Le site principal
`checkupauto.fr` et `www.checkupauto.fr` restent hors pilote.

**Interrupteur de sécurité** : définir
`CYBERCHECK_PUBLIC_IMAGE_CDN_ORIGIN=off` dans l'environnement Passenger
puis redémarrer le processus pour revenir aux médias locaux sans rollback
Git/DNS. Une valeur vide bloque également l'option. Les valeurs explicites
acceptées sont seulement `https://checkupauto-fr.pages.dev` et
`https://static.checkupauto.fr`, sans chemin et sans variante HTTP.

Contrôle après déploiement RemoteOps : vérifier que HTML `GET /` du
staging contient le CDN dans `src`, `srcset`, `imagesrcset`, que
`GET /compte`, `/auth/customer/google`, `/auth/customer/apple`,
`/api/customer/*` restent dirigés vers la même origine et que les temps
de chargement réels ne régressent pas. Pour juger le gain des images,
comparer LCP et octets CDN côté iPhone, pas le temps de connexion OAuth.

## Étape 2 : CSS/JS et CDN complet

Après qualification des images, considérer CSS/JS sur Pages sous contrat :
adaptation des CSP (`script-src`, `style-src`, `connect-src` si besoin),
SRI pour JS versionnés, références relatives CSS/imports, CSS d'abord,
tests des navigateurs Chromium et WebKit. Réserver l'intégration CDN
complet de `test.checkupauto.fr` à une migration DNS exhaustive via
RemoteOps, après sauvegarde N0C, DNSSEC/DS, certificat Full (strict) et
tests d'intégration. **Ne pas activer « Cache Everything »**.

## Sources du fournisseur (vérifiées le 15 octobre 2026)

- https://developers.cloudflare.com/pages/configuration/custom-domains/
- https://developers.cloudflare.com/pages/platform/limits/
- https://developers.cloudflare.com/pages/functions/pricing/
- https://developers.cloudflare.com/pages/configuration/serving-pages/
- https://developers.cloudflare.com/cache/troubleshooting/dynamic-content-and-login-issues/
