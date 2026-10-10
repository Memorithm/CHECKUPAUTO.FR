# Configuration de bordure : origine publique et adresse IP cliente

Ce document décrit les deux réglages d’exécution introduits par l’audit de sécurité
du 10/10/2026 (constats S-01 et S-04). Ils se règlent par variables d’environnement
(`/root/CyberCheckPrivate/runtime.env` pour le service systemd, `environment:` pour
Docker, variables d’application pour Passenger).

## Origine publique des liens envoyés hors requête (S-01)

Les liens envoyés par e-mail (confirmation de compte, réinitialisation de mot de
passe) et le lien de réclamation de cagnotte mobile ne sont **plus** construits à
partir de l’en-tête `Host` de la requête.

| Variable | Défaut | Rôle |
|---|---|---|
| `CYBERCHECK_PUBLIC_ORIGINS` | `https://www.checkupauto.fr,https://checkupauto.fr,https://test.checkupauto.fr` | Liste d’origines `https://hôte[:port]` séparées par des virgules. La première est canonique. L’hôte de la requête n’est réutilisé que s’il figure dans cette liste ; sinon la première origine est utilisée. |

Exemples :

- production : laisser le défaut, ou `CYBERCHECK_PUBLIC_ORIGINS=https://www.checkupauto.fr` ;
- préproduction : `CYBERCHECK_PUBLIC_ORIGINS=https://test.checkupauto.fr` ;
- staging Docker : déjà réglé dans `deploy/hostinger/docker-compose.yml` sur `https://${CHECKUPAUTO_STAGING_HOST}`.

Le parcours OIDC (Google/Apple) continue d’utiliser l’hôte de la requête pour son
`redirect_uri`, car les fournisseurs n’acceptent que les URI enregistrées.

## Adresse IP cliente pour la Sentinel (S-04)

La limitation de débit, les quarantaines et l’anti-force brute utilisent l’adresse du
pair TCP. Un en-tête de transfert n’est lu **que** si le pair direct appartient à un
proxy de confiance.

| Variable | Défaut | Rôle |
|---|---|---|
| `CYBERCHECK_TRUSTED_PROXIES` | `127.0.0.0/8,::1/128` | Réseaux (CIDR) des proxys autorisés à transmettre l’IP cliente. `none` désactive toute confiance. |
| `CYBERCHECK_CLIENT_IP_HEADER` | `cf-connecting-ip` | En-tête lu depuis un proxy de confiance : `cf-connecting-ip`, `x-forwarded-for` (entrée la plus à droite) ou `none`. |

Configurations attendues :

- **Production systemd + Cloudflare Tunnel** (`cloudflared` sur la même machine, connexion
  en boucle locale) : le défaut convient. Vérifier que `cloudflared` pointe bien vers
  `http://127.0.0.1:8765` et qu’aucun autre service local ne relaie du trafic Internet
  vers ce port.
- **Staging Docker derrière Traefik/Coolify** : réglé dans le compose
  (`10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` + `x-forwarded-for`). Si Traefik est
  lui-même derrière Cloudflare, configurer `forwardedHeaders.trustedIPs` de Traefik
  avec les plages Cloudflare.
- **Passenger (PlanetHoster)** : la passerelle transmet `REMOTE_ADDR` comme pair. Si le
  site est servi derrière Cloudflare, `REMOTE_ADDR` est une IP Cloudflare : définir
  `CYBERCHECK_TRUSTED_PROXIES` avec les plages publiées sur
  <https://www.cloudflare.com/ips/> et garder `cf-connecting-ip`. Sinon, le défaut convient.
