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
DEPLOY_SHA="$(basename "$RELEASE")"
if [[ ! "$DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "STAGING_RELEASE_SHA_INVALID"
  exit 29
fi

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

# The release is a RemoteOps-approved `git archive <sha>` and intentionally has
# no .git directory. Materialize only the minimal, non-secret immutable revision
# proof before the image is built so the running surface can attest its release.
python3 "$RELEASE/deploy/hostinger/write-deployment-provenance.py" "$RELEASE" "$DEPLOY_SHA"

ln -sfn "$RELEASE" "$CURRENT"

cd "$CURRENT/deploy/hostinger"
export CHECKUPAUTO_STAGING_HOST="$HOST"
export CHECKUPAUTO_IMAGE_TAG="$DEPLOY_SHA"
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
body="$(mktemp /tmp/checkupauto-stage-body.XXXXXX)"
provenance_body="$(mktemp /tmp/checkupauto-stage-provenance.XXXXXX)"
trap 'rm -f "$body" "$provenance_body"' EXIT
verified=0
for _ in $(seq 1 30); do
  : >"$body"
  if code="$(curl -fsS -o "$body" -w '%{http_code}' --max-time 10 "https://$HOST/")"; then
    if [ "$code" = 200 ] && grep -qi 'checkup' "$body"; then
      verified=1
      break
    fi
  fi
  sleep 3
done
if [ "$verified" -ne 1 ]; then
  echo "STAGING_TRUSTED_HTTPS_NOT_READY=$HOST"
  exit 32
fi

# A healthy page is not enough: prove that HTTPS is serving the exact immutable
# release approved by RemoteOps. The artifact contains only public revision
# metadata and is generated from the validated release-directory SHA above.
if ! curl -fsS --max-time 10 \
  "https://$HOST/assets/cybercheck-deployment-provenance.bin" \
  -o "$provenance_body"; then
  echo "STAGING_DEPLOYMENT_PROVENANCE_NOT_READY=$HOST"
  exit 33
fi
python3 - "$provenance_body" "$DEPLOY_SHA" <<'PY'
import json
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
expected = sys.argv[2]
if re.fullmatch(r"[0-9a-f]{40}", expected) is None:
    raise SystemExit(1)
raw = path.read_bytes()
if len(raw) > 4096:
    raise SystemExit(1)
payload = json.loads(raw.decode("utf-8"))
if not isinstance(payload, dict):
    raise SystemExit(1)
required = {
    "schemaVersion": 1,
    "surface": "checkupauto-cybercheck",
    "purpose": "public-deployment-provenance",
    "verified": True,
    "state": "verified",
    "gitSha": expected,
    "branch": "main",
    "clean": True,
    "source": "remoteops-approved-git-archive",
}
if any(payload.get(key) != value for key, value in required.items()):
    raise SystemExit(1)
PY

echo "STAGING_DEPLOYMENT_PROVENANCE_VERIFIED=$DEPLOY_SHA"
printf 'CHECKUPAUTO_STAGING_DEPLOY_OK\nhost=%s\nrelease=%s\n' "$HOST" "$DEPLOY_SHA"
