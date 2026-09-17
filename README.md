# CHECKUPAUTO.FR / CyberCheck

Private source repository for the Checkup Auto / CyberCheck website and its operational control plane.

The project currently includes:
- the public Checkup Auto website;
- the interactive Mercure RDV availability planner;
- online booking restricted to the authorised 80 EUR and 90 EUR services;
- native Mercure promotion-slot integration;
- first-party cookieless acquisition analytics;
- Mercure live operational dashboards;
- local SEO / 50.01 km geographic targeting components;
- CyberCheck Sentinel request filtering and security telemetry;
- the isolated security AI supervisor;
- Google Search Console integration hooks.

## Local runtime

The reference working directory is `/root/CyberCheckLive`.

Create the virtual environment and install dependencies:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
Start the local application server with:

```bash
.venv/bin/python admin_server.py
```

The application listens on `127.0.0.1:8765` by design. Production/public exposure should be provided by a reverse proxy or Cloudflare Tunnel rather than binding the Python server directly to the Internet.

## Secrets and private state

Runtime credentials are intentionally excluded from Git. In particular, never commit:
- `.admin-password`;
- `private/` and Mercure session cookies;
- webhook secrets or Google service-account keys;
- analytics/security SQLite databases;
- logs, Cloudflare Tunnel binaries or temporary tunnel state.

The repository must remain deployable without embedding any credential in source control.

## Source of truth

`main` is the canonical source branch. Local operational state is not part of the source tree contract. Changes should be tested locally, committed, then pushed to `origin/main`.
