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

# security_integrity intentionally refuses to invent its own first baseline at
# application startup. Provision it as a distinct root-controlled deployment
# step against the exact image that will be started, then return ownership to
# the unprivileged runtime UID/GID used by the image.
docker compose run --rm --no-deps --user 0:0 web \
  python -c 'import security_integrity; security_integrity.create_baseline(True)'
test -s "$STATE/integrity/integrity-baseline.json"
chown 10001:10001 "$STATE/integrity/integrity-baseline.json"
chmod 0640 "$STATE/integrity/integrity-baseline.json"

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

code="$(curl -sS -o /tmp/checkupauto-stage-body -w '%{http_code}' --max-time 20 "https://$HOST/")"
echo "staging_http_code=$code"
test "$code" = 200
grep -qi 'checkup' /tmp/checkupauto-stage-body
rm -f /tmp/checkupauto-stage-body

printf 'CHECKUPAUTO_STAGING_DEPLOY_OK\nhost=%s\nrelease=%s\n' "$HOST" "$(basename "$RELEASE")"
