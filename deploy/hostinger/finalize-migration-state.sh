#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/srv/checkupauto/staging
STATE="$ROOT/state"
CURRENT="$ROOT/current"
CONTAINER=checkupauto-staging-web
HOST="${CHECKUPAUTO_STAGING_HOST:-stage.179.198.210.187.sslip.io}"

if [ "$#" -ne 2 ] || [ "$1" != "--confirm" ] || [ "$2" != "ACTIVATE_MIGRATED_STATE" ]; then
  echo "HOSTINGER_MIGRATION_FINALIZE_CONFIRMATION_REQUIRED"
  exit 70
fi

test -L "$CURRENT"
release="$(realpath -e "$CURRENT")"
case "$release" in
  "$ROOT"/releases/*) ;;
  *)
    echo "HOSTINGER_MIGRATION_CURRENT_RELEASE_INVALID"
    exit 71
    ;;
esac
sha="$(basename "$release")"
if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "HOSTINGER_MIGRATION_RELEASE_SHA_INVALID"
  exit 71
fi

tool="$release/migration_write_freeze.py"
test -f "$tool"
export CYBERCHECK_DATA_DIR="$STATE/data"

python3 - "$release" <<'PY'
from pathlib import Path
import sys

release=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(release))
import migration_write_freeze

state=migration_write_freeze.status()
if not state.get("active") or not state.get("valid") or state.get("state")!="frozen":
    raise SystemExit("migration state is not validly frozen")
print("HOSTINGER_MIGRATION_PRE_FINALIZE_FREEZE_VERIFIED")
PY

running="$(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || printf 'false')"
health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER" 2>/dev/null || true)"
if [ "$running" != "true" ] || [ "$health" != "healthy" ]; then
  echo "HOSTINGER_MIGRATION_FROZEN_RUNTIME_NOT_HEALTHY"
  exit 72
fi

cd "$release/deploy/hostinger"
export CHECKUPAUTO_STAGING_HOST="$HOST"
export CHECKUPAUTO_IMAGE_TAG="$sha"

docker compose stop web
if [ "$(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || printf 'false')" = "true" ]; then
  echo "HOSTINGER_MIGRATION_CONTAINER_STOP_FAILED"
  exit 73
fi

rollback() {
  set +e
  CYBERCHECK_DATA_DIR="$STATE/data" python3 "$tool" freeze --reason hostinger_finalize_failed >/dev/null 2>&1
  docker compose stop web >/dev/null 2>&1
  echo "HOSTINGER_MIGRATION_FINALIZE_ROLLED_BACK_TO_FREEZE" >&2
}
trap rollback ERR

python3 "$tool" unfreeze --confirm UNFREEZE

docker compose run --rm --no-deps web \
  python -c 'import admin_server; state=admin_server.initialize_runtime(background=False); assert state.get("coreReady") is True and state.get("writeFrozen") is False; print("MIGRATED_RUNTIME_CORE_READY")'

docker compose up -d --no-deps web

healthy=0
for _ in $(seq 1 45); do
  state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER" 2>/dev/null || true)"
  if [ "$state" = "healthy" ]; then
    healthy=1
    break
  fi
  sleep 2
done
if [ "$healthy" -ne 1 ]; then
  docker logs --tail 120 "$CONTAINER" || true
  false
fi

body="$(mktemp /tmp/checkupauto-finalize-body.XXXXXX)"
provenance="$(mktemp /tmp/checkupauto-finalize-provenance.XXXXXX)"
cleanup() {
  rm -f "$body" "$provenance"
}
trap 'cleanup; rollback' ERR
trap cleanup EXIT

curl -fsS --max-time 10 "https://$HOST/" -o "$body"
grep -qi 'checkup' "$body"
curl -fsS --max-time 10 "https://$HOST/assets/cybercheck-deployment-provenance.bin" -o "$provenance"
python3 - "$provenance" "$sha" <<'PY'
import json
from pathlib import Path
import re
import sys

payload=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected=sys.argv[2]
if re.fullmatch(r"[0-9a-f]{40}",expected) is None:
    raise SystemExit(1)
required={
    "schemaVersion":1,
    "surface":"checkupauto-cybercheck",
    "purpose":"public-deployment-provenance",
    "verified":True,
    "state":"verified",
    "gitSha":expected,
    "branch":"main",
    "clean":True,
    "source":"remoteops-approved-git-archive",
}
if not isinstance(payload,dict) or any(payload.get(k)!=v for k,v in required.items()):
    raise SystemExit(1)
PY

python3 - "$release" <<'PY'
from pathlib import Path
import sys

release=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(release))
import migration_write_freeze

state=migration_write_freeze.status()
if state.get("active") or not state.get("valid") or state.get("state")!="inactive":
    raise SystemExit("migration state unexpectedly frozen after finalize")
print("HOSTINGER_MIGRATION_UNFREEZE_VERIFIED")
PY

trap - ERR
echo "HOSTINGER_MIGRATION_STATE_ACTIVE=$sha"
