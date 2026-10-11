# Transfert vers Mercure (rdv.checkupauto.fr) : ce qui peut être pré-rempli

Constats du 11 octobre 2026, obtenus en lecture seule : affichage de `/prendre_rdv` et lecture de son JavaScript intégré. Aucune étape de validation n'a été soumise.

## Ce que Mercure accepte

| Élément | Possible ? | Preuve |
| --- | --- | --- |
| Prestation | **Oui** (déjà utilisé) | `POST /prendre_rdv` avec `id=240` et `prestation=LIBELLÉ\|id\|tarif\|durée\|1`. Le serveur recopie la valeur dans `#prestation_sel`. Au chargement, `select_prestation(...)` affiche directement l'onglet des dates. |
| Date ou créneau | **Non** | `#DateHid` est fixé par le serveur à la date du jour. `recherche_dispo()` lit uniquement ce champ. `Date_rdv` et `Heure_rdv` ne sont remplis que par `select_heure(...)`, au clic sur un créneau. Les paramètres `date`, `DateHid`, `date_rdv`, `heure`, `Heure_rdv`, en GET comme en POST, sont ignorés : la page rendue est identique hors jeton CSRF. |
| Identité et contact | **Non** | `nom`, `prenom`, `telephone` et `email` sont rendus vides. Aucun paramètre n'est recopié. |
| Véhicule | **Non** | `marque`, `modele`, `energie` et `immatriculation` sont rendus vides, et `modele` est chargé en AJAX d'après la marque. |
| Paramètres d'URL lus par le JavaScript | `errorLogin`, `iframe` uniquement | `URLSearchParams` n'est utilisé que pour ces deux clés. |
| Communication entre origines | **Non** | Aucun écouteur `message` (`postMessage`), aucun `location.hash`, aucun `localStorage` ni `sessionStorage`. |
| Cookies | **Non** | `PHPSESSID` est propre au domaine rdv.checkupauto.fr et lié à sa session : notre site ne peut ni le lire ni l'écrire. |
| Étapes serveur préalables | **Exclues** | L'étape suivante, `POST /add_rendezvous_client_libre`, **crée le rendez-vous**. Elle est interdite hors du chemin d'écriture qualifié (parcours sur site, désactivé). |

Contraintes de saisie observées dans Mercure :

- téléphone : chiffres uniquement, 10 au minimum ;
- immatriculation au format `AA-999-AA` ;
- énergie : Diesel, Essence, Hybride, Electrique ou GPL/GN.

## Ce que fait désormais `/go/booking` pour un client connecté

- **Prestation** : présélectionnée comme avant, le formulaire envoyé à Mercure est inchangé (`id`, `prestation`).
- **Bloc « Vos informations à reporter dans Mercure »**, sur notre page :
  - le créneau choisi en toutes lettres, avec la consigne d'avancer jusqu'à cette date ;
  - nom, prénom, téléphone (au format Mercure, `+33` converti), e-mail, marque, modèle, énergie et immatriculation ;
  - un bouton « Copier » pour chaque valeur.
- **Ouverture dans un nouvel onglet** : Mercure s'ouvre dans un onglet ouvert pendant le clic (`opener` neutralisé), ce qui laisse cette page disponible pour copier. Si le navigateur refuse l'ouverture, Mercure s'ouvre dans l'onglet courant, comme avant.
- **Confidentialité** : aucune donnée personnelle n'est ajoutée au formulaire ni à l'URL envoyés à Mercure, ni aux journaux. Les valeurs ne sont affichées qu'au client connecté, sur une page `no-store`.
- **Textes inchangés** : CGV, exécution immédiate, preuve d'acceptation.

Sans profil exploitable, la page est identique à la précédente. Les visiteurs non connectés sont, comme avant, redirigés vers la connexion.

## Pour aller plus loin

Deux options existent :

- Demander à l'éditeur de Mercure de reprendre, à l'ouverture de `/prendre_rdv`, des champs postés tels que `date_rdv`, `heure_rdv`, `nom`, `prenom`, `telephone`, `email`, `immatriculation`, `marque`, `modele` et `energie`. Il suffirait de les recopier dans les champs existants et d'appeler `select_heure`.
- Activer le parcours sur site, documenté dans `reservation-sur-site.md`, une fois les décisions prises.
