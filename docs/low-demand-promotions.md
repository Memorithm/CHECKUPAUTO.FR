# Offres sur les créneaux historiquement calmes

## Lecture et ciblage

L’historique de Check Up Auto est consulté dans Mercure sur 84 jours révolus et regroupé uniquement par jour de semaine et heure. Mercure utilise des dates françaises (JJ/MM/AAAA HH:MM) et des codes de prestations (CTP, VTP, CV) ; le moteur mesure donc l’occupation du centre, toutes prestations confondues, sans deviner leur nomenclature.

Une heure est jugée peu demandée si au moins 20 rendez-vous ont eu lieu ce jour de semaine, si l’heure la plus occupée en compte au moins 5, et si son activité corrigée est inférieure ou égale à la moitié de celle de l’heure de pointe avec un écart minimum de 3 rendez-vous. L’historique n’est conservé que sous forme de compteurs agrégés (cache 4 heures) : aucune plaque, identité ni coordonnée personnelle.

La flamme et le libellé CRÉNEAU CALME ne sont visibles que par un client connecté sur un horaire réellement disponible, avec une réduction constatée directement auprès de Mercure d’au moins 5 €. Maximum deux flammes par journée affichée. Pas de flamme si l’historique manque, si l’utilisateur est anonyme, si la politique interdit la remise ou si le fournisseur ne confirme pas le prix.

## Remises automatiques

La publication est DÉSACTIVÉE par défaut. Seul un contrôleur de production expressément habilité avec la variable d’environnement CYBERCHECK_LOW_DEMAND_PROMO_PUBLISH=1 peut envoyer une promotion à Mercure. Ne pas activer cette option sur plusieurs serveurs, sur une instance de staging, ou durant un gel de migration.

Sous ces conditions, le worker passe à son démarrage puis toutes les 12 heures, utilise les disponibilités actuelles des 1 à 6 prochains jours, publie au maximum 2 offres par jour et 4 par passage, évite les doublons d’un même horaire physique entre prestations, et demande une baisse de 5 € (80 → 75 € ; 90 → 85 €). Chaque tentative est enregistrée avant l’écriture fournisseur. Aucune réponse ambiguë ne déclenche de réessai aveugle. Après publication, une nouvelle lecture sans cache vérifie le prix réel.

Le prix est affiché dans le planning et vérifié à nouveau dans la page récapitulative depuis l’API Mercure, sans accepter de montant issu du navigateur. La réservation passe toujours par compte, véhicule et acceptation des CGV. Le site ne verrouille pas encore le créneau chez Mercure : le client doit sélectionner le même horaire dans le planning final du fournisseur. Le prix définitif est celui confirmé par Mercure avant paiement.

## Exploitation / validation

La route administrateur /api/admin/mercure/status affiche le statut du worker sans donnée nominative. Tests locaux : python3 -m unittest -v booking_demand_test booking_contract_acceptance_test. Aucun mot de passe ni cookie fournisseur n’est présent dans le dépôt.

Activation ultérieure exclusivement depuis le plan de contrôle RemoteOps après validation de la CI, du tarif sur Mercure et du déploiement staging. Arrêt : supprimer la variable sur le contrôleur et redémarrer le service. Les offres déjà créées restent sous l’administration Mercure et nécessitent, si besoin, une annulation explicite de leur part.
