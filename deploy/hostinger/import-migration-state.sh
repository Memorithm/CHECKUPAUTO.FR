#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/srv/checkupauto/staging
STATE="$ROOT/state"
CURRENT="$ROOT/current"
INCOMING_ROOT="$ROOT/migration-incoming"
CONTAINER=checkupauto-staging-web

test "$#" -eq 1
install -d -m 0700 "$INCOMING_ROOT"

snapshot="$(realpath -e "$1")"
case "$snapshot" in
  "$INCOMING_ROOT"/*) ;;
  *)
    echo "HOSTINGER_MIGRATION_SNAPSHOT_OUTSIDE_INCOMING_ROOT"
    exit 64
    ;;
esac
if [ -L "$1" ] || [ ! -d "$snapshot" ]; then
  echo "HOSTINGER_MIGRATION_SNAPSHOT_INVALID"
  exit 64
fi

running="$(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || printf 'false')"
if [ "$running" = "true" ]; then
  echo "HOSTINGER_MIGRATION_IMPORT_REFUSED_CONTAINER_RUNNING"
  exit 65
fi

test -L "$CURRENT"
release="$(realpath -e "$CURRENT")"
case "$release" in
  "$ROOT"/releases/*) ;;
  *)
    echo "HOSTINGER_MIGRATION_CURRENT_RELEASE_INVALID"
    exit 66
    ;;
esac

tool="$release/scripts/checkupauto-migration-state.py"
test -f "$tool"
python3 "$tool" verify --snapshot "$snapshot"
python3 "$tool" import \
  --snapshot "$snapshot" \
  --target-root "$STATE" \
  --uid 10001 \
  --gid 10001

CYBERCHECK_DATA_DIR="$STATE/data" python3 - "$release" <<'PY'
from pathlib import Path
import os
import sys

release=Path(sys.argv[1]).resolve()
if str(release) not in sys.path:
    sys.path.insert(0,str(release))
import migration_write_freeze

state=migration_write_freeze.status()
if not state.get("active") or not state.get("valid") or state.get("state")!="frozen":
    raise SystemExit("imported migration freeze marker invalid")
print("HOSTINGER_MIGRATION_FREEZE_VERIFIED")
PY

rm -rf -- "$snapshot"
echo "HOSTINGER_MIGRATION_SNAPSHOT_REMOVED"
echo "HOSTINGER_MIGRATION_STATE_IMPORTED"
