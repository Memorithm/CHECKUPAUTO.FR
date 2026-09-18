# Distribution de l’application iOS Checkup Auto

## Principe

Les QR codes ne pointent jamais directement vers l’App Store. Ils pointent vers une URL Checkup Auto permanente :

- site : `https://checkupauto.fr/app?src=qr-site`
- centre : `https://checkupauto.fr/app?src=qr-centre`
- lien éditorial du site : `https://checkupauto.fr/app?src=site`

La page `/app` reste stable avant et après la publication. Quand l’application est disponible, `/go/app` redirige vers l’URL App Store configurée côté serveur.

## Sécurité

`CYBERCHECK_IOS_APP_URL` est lu depuis l’environnement du serveur. Seules les URL HTTPS dont l’hôte exact est `apps.apple.com` sont acceptées. Une autre valeur laisse l’application en état « bientôt disponible » et ne déclenche aucune redirection externe.

Le fichier systemd charge déjà `/root/CyberCheckPrivate/runtime.env`; aucune URL de distribution n’a donc besoin d’être inscrite dans le dépôt.

## Mesure de provenance

Deux événements cookieless sont ajoutés à l’analytics interne :

- `app_landing_view` : visite de `/app` ;
- `app_store_click` : clic/redirection vers l’App Store.

La provenance est conservée sous la forme `app:site`, `app:qr-site` ou `app:qr-centre`. Cela permet de comparer l’efficacité du site et de l’affichage physique sans tracer l’identité du visiteur.

## Supports générés

- `assets/app/qr-site.svg` : QR à utiliser sur le site ;
- `assets/app/qr-centre.svg` : QR destiné aux supports imprimés ;
- `assets/app/centre-poster.svg` : affiche A5 de centre.
