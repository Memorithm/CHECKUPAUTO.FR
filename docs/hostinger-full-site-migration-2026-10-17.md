# CheckupAuto — migration intégrale vers Hostinger (préparation du 17 octobre 2026)

> État : préparation documentée, **aucune bascule DNS, aucune mutation de données ni activation de production autorisée par ce document**.
> Plan de contrôle distant : [Memorithm/RemoteOps](https://github.com/Memorithm/RemoteOps). Source de vérité fonctionnelle : [CHECKUPAUTO.FR](https://github.com/Memorithm/CHECKUPAUTO.FR).

## Périmètre réel

- Déplacer le site CheckupAuto (pages publiques, espace client, API, réservation intégrée, assets, informations légales, rappels et opérations automatisées) vers le VPS Hostinger KVM 4 déjà documenté dans `RemoteOps/docs/hostinger-checkupauto-kvm4.md`.
- Conserver le parcours Mercure/Payline existant avec le centre comme autorité des créneaux, confirmations et paiements ; le déploiement web n'est pas une migration de la base propriétaire Mercure.
- Protéger les identités Google/Apple, les sessions iOS, les notifications/APNs et les callbacks de paiement contre un changement d'origine non coordonné.
- Ne jamais déplacer les MX, SPF, DKIM, DMARC ou le domaine `rdv.checkupauto.fr` sans accord et qualification séparés. Préserver les services indépendants tant qu'un substitut n'est pas validé.

## Inventaire et preuves disponibles au 17 octobre 2026

| Composant | Constat vérifiable | Critère avant bascule |
| --- | --- | --- |
| Hostinger | VPS KVM 4 et staging `stage.179.198.210.187.sslip.io` ; déploiement Compose via `deploy/hostinger/docker-compose.yml` | Provenance exacte du SHA, TLS validé et runtime stable |
| Réplication PlanetHoster | Miroir SQLite incrémental par timer Hostinger, documenté dans `RemoteOps/docs/hostinger-checkupauto-kvm4.md` | Dernier miroir signé/vérifié, frais (< 45 min à l'application), restauration testée |
| Surveillance Hostinger | [Run 39009139576](https://github.com/Memorithm/RemoteOps/actions/runs/39009139576) **success avec avertissement** ; `api:admin-readiness` dégradé, `launchReady=False` | Rapport sans blocage critique, `launchReady=True` constaté sur le runtime de destination |
| Gate staging | [Run 38963030214](https://github.com/Memorithm/CHECKUPAUTO.FR/actions/runs/38963030214) terminé `success` | Nouveau gate vert sur le SHA final de production |
| Parité des origines | [Run 39002308342](https://github.com/Memorithm/RemoteOps/actions/runs/39002308342) **failure** : script `http_404` pour l'origine Thor | Réparer et revérifier la parité sans diminuer la couverture de contrôle |
| PostgreSQL chez PlanetHoster | [Run 38975714740](https://github.com/Memorithm/RemoteOps/actions/runs/38975714740) : `service_missing`, fichier privé `.pg_service.conf` absent | Qualifier séparément la base existante avant tout transfert ; **ne pas recréer** la base |

Le chantier PostgreSQL de `docs/customer-postgresql-rollout.md` est **distinct** de la bascule Hostinger actuellement basée sur le miroir SQLite. Une erreur de précontrôle PostgreSQL n'autorise pas à importer un schéma ni à remplacer les comptes en production.

## Séquence exécutable par RemoteOps — portes obligatoires

1. **Inventaire sans écriture** : enregistrer les SHAs exacts du site et de RemoteOps ; exporter de manière sécurisée la zone DNS autoritative complète chez l'opérateur actuel ; constater les enregistrements `@`, `www`, `test`, `rdv`, `mail`, MX/TXT/CAA, TTL, services tiers et callbacks OAuth/Payline. Conserver cet inventaire hors dépôt si confidentiel.
2. **Qualifier l'environnement final** : image reproductible, certificat TLS valide pour chaque hôte public, isolation des secrets, environnement production distinct de staging, journalisation sans données personnelles, restauration chiffrée démontrée, accès administrateur MFA, alertes et réponse aux incidents.
3. **Corriger le défaut de préparation** : exécuter les diagnostics RemoteOps de readiness et de blocages, lever `launchReady=False` et les erreurs de parité d'origine. Aucun statut `success` du moniteur seul ne suffit : lire et traiter aussi ses avertissements.
4. **Valider le parcours de bout en bout sur l'origine Hostinger sans changer le DNS** : compte (création, connexion, déconnexion, Google/Apple), véhicules et échéances, autorisation Mercure, créneau et retour Payline, confirmation côté centre, e-mail, APNs et Dynamic Island, exports et suppression RGPD, limites de débit, p95 et disponibilité.
5. **Sécuriser l'état** : obtenir une sauvegarde restaurable du site ancien et de l'état Hostinger ; vérifier le dernier miroir et son intégrité. Geler les écrivains de l'ancien système ; garder le gel actif jusqu'au cutover atomique. Ne pas faire de réplication SQLite bidirectionnelle.
6. **Importer sur Hostinger** : utiliser uniquement les scripts existants `RemoteOps/ops/hostinger-apply-db-mirror.sh` et `deploy/hostinger/import-migration-state.sh` sous les contrôles de release ; conserver le reçu et le rollback. `deploy/hostinger/finalize-migration-state.sh` ne peut être exécuté qu'après contrôles et approbation explicite de l'activation.
7. **Basculer le web** : après TLS vérifié sur IP Hostinger avec le bon SNI, enregistrer le changement de zone et ne modifier que les enregistrements web nécessaires, sans toucher au mail ni aux routes Mercure. Attendre l'ancien TTL avant d'inférer la propagation.
8. **Contrôler et accepter** : HTTPS, disponibilité, comptes et paiements réels autorisés, parcours clients anciens et nouveaux, journaux sans secrets, DNS autoritatifs/publics, e-mail, retour des callbacks et métriques. Conserver une fenêtre de surveillance et les preuves de réception Mercure.
9. **Retour arrière sans perte** : ne restaurer l'ancien A que si la cohérence des écritures post-bascule est assurée ; sinon geler les deux côtés et arrêter toute écriture pour réconcilier d'abord. Une réouverture de l'ancien site en écriture après activation du nouveau risquerait de créer un split-brain.

## Garde-fous de production

- Le fichier `deploy/hostinger/docker-compose.yml` est configuré pour **staging** (`CYBERCHECK_RUNTIME_ENV=staging`, `CYBERCHECK_PAYMENT_TEST_ENABLED=1`, prévisualisation promotionnelle). Il ne doit **jamais** être exposé tel quel comme environnement de production.
- La configuration finale doit employer un service, un état, des secrets, une origine et des domaines de production distincts ; les capacités de paiement en test et les panneaux de préproduction doivent être explicitement désactivés.
- `test.checkupauto.fr` doit rester un espace de vérification ; `rdv.checkupauto.fr` demeure le fournisseur de planning existant tant qu'un transfert autonome de Mercure n'est ni autorisé ni prouvé.
- Les jetons OAuth, clés APNs/Payline, clés du miroir et données clients restent sur les hôtes autorisés. Jamais dans Git, les artefacts Actions ou les logs.
- Aucun merge, déploiement ou changement DNS sans CI verte au SHA exact et sans contrôles de sécurité conformes à `AGENTS.md`.

## Contrôles à exécuter, sans intervention DNS

Sur Debian 12 avec `gh` connecté au compte autorisé :

```bash
gh run view 39009139576 -R Memorithm/RemoteOps
gh run view 39002308342 -R Memorithm/RemoteOps
gh run view 38963030214 -R Memorithm/CHECKUPAUTO.FR
gh run view 38975714740 -R Memorithm/RemoteOps
```

Ces commandes **lisent** l'historique GitHub et ne déclenchent ni accès aux données client ni action de production.

## Décision de bascule

**NON AUTORISÉE au 17 octobre 2026** : le moniteur Hostinger signale `launchReady=False`. La production actuelle reste inchangée. Relancer la qualification avec des preuves fraîches avant de proposer une fenêtre de bascule.

Sources de référence : `RemoteOps/docs/hostinger-checkupauto-kvm4.md`, `RemoteOps/ops/checkupauto-hostinger-readiness.py`, `RemoteOps/ops/checkupauto-hostinger-sentinel.py`, `RemoteOps/ops/checkupauto-domain-readiness.py`, `docs/customer-access-and-domain-migration.md`, `docs/customer-postgresql-rollout.md`, `deploy/hostinger/`.
