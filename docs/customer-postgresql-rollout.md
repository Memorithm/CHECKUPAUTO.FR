# PostgreSQL 16 — phase 1, espace client CHECKUPAUTO

**Statut : préparation de migration isolée, NON activée sur le site.**
Le runtime Passenger continue à utiliser SQLite tant qu'une phase 2 dédiée
n'a pas été développée, vérifiée et déployée par RemoteOps. Ne pas changer
la base des clients ou des paiements par simple variable d'environnement.
Le domaine public `www.checkupauto.fr` et `rdv.checkupauto.fr` restent inchangés.

## Périmètre

- Schéma PostgreSQL dans `ops/postgres/customer-schema.sql`.
- Sept tables de comptes clients, identités, sessions, mots de passe et validation
  de passage; deux tables de flux OIDC/nonce natif.
- `profile_blob` reste un BYTEA **chiffré à l'identique**, jamais déchiffré.
- Le transfert préserve exactement les hachages des identifiants, sessions,
  mots de passe et clés des jetons; jamais de journal de données.
- Les autres bases (Mercure, paiements, notifications, conformité, mobile,
  audit et droits RGPD) **ne sont pas encore migrées**.

## Conditions nécessaires avant toute copie

1. Confirmer une instance PostgreSQL 16 *réellement disponible* sur le
   projet PlanetHoster de préproduction (N0C). Ne pas supposer qu'un produit
   proposé au catalogue est activé sur notre abonnement.
2. Créer une base **distincte** et un rôle PostgreSQL propre à la
   préproduction; ne pas partager les droits des comptes de production.
   Activer TLS avec validation du serveur et certificat CA.
3. Installer `psycopg` dans un environnement **de maintenance isolé**,
   après approbation d'une version/verrouillage reproductible. Le serveur
   Web n'en a pas besoin tant que son backend demeure SQLite.
4. Effectuer et tester une **sauvegarde chiffrée récupérable** des deux
   fichiers SQLite. Aucun dump contenant des données clients ne doit être
   commité, envoyé à GitHub ou placé dans un répertoire public.
5. Bloquer tous les écrivains (travaux planifiés inclus), déclencher la
   suspension contrôlée `migration_write_freeze` sur staging et vérifier
   qu'elle est valide. Les deux sources SQLite doivent rester disponibles
   localement en lecture seule, sans lien symbolique.

## Préparation isolée

Avec un client PostgreSQL et un service libpq nommé, dont les secrets sont
stockés hors du dépôt et sous contrôle d'accès strict :

```bash
export PGSERVICE=checkupauto_staging
export PGSSLMODE=verify-full
export PGSSLROOTCERT=/chemin-prive/ca-postgres.pem
psql -v ON_ERROR_STOP=1 -f ops/postgres/customer-schema.sql
```

Sur des copies **isolées**, lancer le précontrôle local, sans aucune connexion
PostgreSQL ni écriture :

```bash
python3 ops/postgres/customer-migrate.py \
  --accounts /chemin-prive/customer-accounts.sqlite3 \
  --oidc /chemin-prive/customer-oidc.sqlite3
```

Sur le *staging réel seulement*, après sauvegarde vérifiée, gel d'écriture
opérationnel, base PostgreSQL vide et `CHECKUPAUTO_ENVIRONMENT=staging`,
l'opérateur habilité peut déclencher la copie transactionnelle :

```bash
python3 ops/postgres/customer-migrate.py \
  --accounts /chemin-prive/customer-accounts.sqlite3 \
  --oidc /chemin-prive/customer-oidc.sqlite3 \
  --apply --confirm STAGING_PG_COPY
```

La copie est intégralement annulée si une table PostgreSQL n'est pas vide,
si un nombre de lignes ou une empreinte de contenu diffère, si un schéma
manque ou si une source change pendant le transfert. Le script ne modifie
jamais les fichiers SQLite et **n'active pas PostgreSQL dans Passenger**.

## Garde de mise en service — phase 2

La bascule fonctionnelle devra reposer sur un backend PostgreSQL explicite
et testé (requêtes, verrous transactionnels, CSRF, sessions, mots de passe,
identités fédérées et flux OIDC à usage unique), avec tests parallèles sous
charge et migration des travaux de rétention. Ne pas fusionner des données
de comptes réels avec des données de test. Aucun retour silencieux vers SQLite
en cas d'indisponibilité PostgreSQL : les erreurs doivent être explicites et
les transactions atomiques. La phase 2 nécessite les contrôles d'acteur
`CHECKUPAUTO`, SHA exact, CI verte, intégrité, rollback et les sondes
d'authentification déjà définies dans RemoteOps.

Critères de sortie : transferts vérifiés en staging, relecture des sessions
et mots de passe, Google/Apple et nonces natifs, nettoyage RGPD, tests
cold/warm et de concurrence, p95 stable et zéro HTTP 503 sur plusieurs
campagnes. Les problèmes TLS/Passenger peuvent être indépendants du SGBD.
