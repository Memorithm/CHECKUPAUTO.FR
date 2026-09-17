# Security policy

CHECKUPAUTO.FR is a private operational repository. Secrets and production state must never be committed.

## Repository rules

- Keep credentials, sessions and databases outside Git and outside the public web root. Runtime secrets belong in `/root/CyberCheckPrivate`.
- Never commit Google service-account JSON, Mercure cookies, webhook secrets or private keys.
- Do not commit runtime logs, temporary Cloudflare Tunnel URLs or binaries.
- Treat all backup files as root-only deployment state under `/root/CyberCheckBackups`.
- Keep the integrity baseline root-owned under `/root/CyberCheckIntegrity`; never expose a web rebaseline action.
- Keep the public web root allow-listed in `security_guard.py`.
- Keep the application server bound to loopback unless an audited reverse proxy is in front of it.

## Defensive architecture

CyberCheck Sentinel performs deterministic filtering, rate control, scanner detection and pseudonymised security telemetry. `security_ai.py` is advisory: it must not receive unrestricted shell, filesystem or firewall privileges.

The production application process must run as the dedicated `cybercheck` system account using `deploy/cybercheck.service`; running the HTTP application as root is prohibited. Integrity rebaselining is a root/offline deployment action and is intentionally not exposed through HTTP.

## Incident handling

Rotate any credential immediately if it is ever committed. Removing a secret from the latest commit is not sufficient; assume Git history and clones may retain it.
