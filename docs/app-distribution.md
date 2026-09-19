# Distribution de l’application iOS Checkup Auto

## Principe

Les QR codes et liens éditoriaux restent sous le domaine Checkup Auto. Ils ne dépendent donc pas d’une URL Apple inscrite en dur dans le site :

- site : `https://checkupauto.fr/app?src=qr-site`
- centre : `https://checkupauto.fr/app?src=qr-centre`
- lien éditorial du site : `https://checkupauto.fr/app?src=site`

La page `/app` est permanente. Son bouton utilise `/go/app`, qui choisit automatiquement la meilleure cible active : App Store public en priorité, TestFlight public pendant la bêta, ou retour vers `/app` lorsque rien n’est encore publié.

## Cycle de distribution

Le backend expose trois états publics dans `/api/app/status` :

- `pending` : aucune distribution Apple n’est configurée ;
- `testflight` : une invitation publique TestFlight est disponible ;
- `app-store` : l’application publique est disponible sur l’App Store.

Lorsque les deux URL sont configurées, l’App Store est toujours prioritaire. Le passage de TestFlight à l’App Store ne nécessite donc aucune modification du site, du QR code ou de l’application : il suffit de configurer l’URL publique App Store côté serveur.

## Configuration et sécurité

Deux variables sont lues depuis l’environnement privé du serveur :

- `CYBERCHECK_IOS_TESTFLIGHT_URL` : lien public `https://testflight.apple.com/join/...` ;
- `CYBERCHECK_IOS_APP_URL` : lien public `https://apps.apple.com/...`.

Les redirections sont sur liste blanche. Le lien App Store doit utiliser HTTPS et l’hôte exact `apps.apple.com`. Le lien TestFlight doit utiliser HTTPS, l’hôte exact `testflight.apple.com` et un chemin `/join/<code>` sans paramètres ni fragment. Une valeur non conforme est ignorée et ne déclenche aucune redirection externe.

Le fichier systemd charge déjà `/root/CyberCheckPrivate/runtime.env`; aucune URL de distribution n’a besoin d’être inscrite dans le dépôt.

## Mesure de provenance

L’analytics interne reste cookieless :

- `app_landing_view` : visite de `/app` ;
- `app_testflight_click` : départ vers TestFlight ;
- `app_store_click` : départ vers l’App Store.

La provenance est conservée sous la forme `app:site`, `app:qr-site` ou `app:qr-centre`. Le résumé analytique expose séparément les clics TestFlight et App Store ainsi que leur somme `appDistributionClicks`. Il devient ainsi possible de comparer le site et l’affichage physique sans stocker l’identité du visiteur.

## Supports générés

- `assets/app/qr-site.svg` : QR à utiliser sur le site ;
- `assets/app/qr-centre.svg` : QR destiné aux supports imprimés ;
- `assets/app/centre-poster.svg` : affiche A5 de centre.

Les supports physiques doivent continuer à pointer vers Checkup Auto, jamais directement vers Apple. Cette indirection permet de conserver le même support durant la phase TestFlight puis après la publication App Store.
