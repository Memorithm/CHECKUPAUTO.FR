#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/srv/checkupauto/staging
RELEASES="$ROOT/releases"
STATE="$ROOT/state"
CURRENT="$ROOT/current"
HOST="${CHECKUPAUTO_STAGING_HOST:-stage.179.198.210.187.sslip.io}"

test "$#" -eq 1
RELEASE="$1"
test -d "$RELEASE"

install -d -m 0750 "$ROOT" "$RELEASES"
for dir in data private security integrity; do
  install -d -o 10001 -g 10001 -m 0700 "$STATE/$dir"
done

if [ ! -s "$STATE/private/admin-password" ]; then
  python3 - <<'PY'
from pathlib import Path
import secrets
p=Path("/srv/checkupauto/staging/state/private/admin-password")
p.write_text(secrets.token_urlsafe(48)+"\n", encoding="utf-8")
p.chmod(0o600)
PY
  chown 10001:10001 "$STATE/private/admin-password"
fi

ln -sfn "$RELEASE" "$CURRENT"

cd "$CURRENT/deploy/hostinger"
export CHECKUPAUTO_STAGING_HOST="$HOST"
export CHECKUPAUTO_IMAGE_TAG="$(basename "$RELEASE")"
docker compose build --pull web

# The integrity supervisor is fail-closed: a freshly built immutable image must
# receive an approved baseline before the long-running server is allowed to start.
docker compose stop web >/dev/null 2>&1 || true
docker compose run --rm --no-deps web \
  python -c 'import security_integrity; security_integrity.create_baseline(True); print("INTEGRITY_BASELINE_PROVISIONED")'

docker compose up -d --remove-orphans

healthy=0
for _ in $(seq 1 45); do
  state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' checkupauto-staging-web 2>/dev/null || true)"
  if [ "$state" = healthy ]; then
    healthy=1
    break
  fi
  sleep 2
done
if [ "$healthy" -ne 1 ]; then
  docker logs --tail 120 checkupauto-staging-web || true
  exit 30
fi

getent ahostsv4 "$HOST" | grep -q '179\.198\.210\.187' || {
  echo "STAGING_DNS_NOT_READY=$HOST"
  exit 31
}

# Traefik can briefly present its default self-signed certificate while ACME is
# obtaining the first trusted certificate for a newly-created staging router.
# Retry the *verified* HTTPS request rather than weakening certificate checks.
body=/tmp/checkupauto-stage-body
verified=0
for _ in $(seq 1 30); do
  rm -f "$body"
  if code="$(curl -fsS -o "$body" -w '%{http_code}' --max-time 10 "https://$HOST/")"; then
    if [ "$code" = 200 ] && grep -qi 'checkup' "$body"; then
      verified=1
      break
    fi
  fi
  sleep 3
done
rm -f "$body"
if [ "$verified" -ne 1 ]; then
  echo "STAGING_TRUSTED_HTTPS_NOT_READY=$HOST"
  exit 32
fi

printf 'CHECKUPAUTO_STAGING_DEPLOY_OK\nhost=%s\nrelease=%s\n' "$HOST" "$(basename "$RELEASE")"
