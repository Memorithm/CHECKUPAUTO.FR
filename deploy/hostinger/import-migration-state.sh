#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=/srv/checkupauto/staging
STATE="$ROOT/state"
CURRENT="$ROOT/current"
INCOMING_ROOT="$ROOT/migration-incoming"
CONTAINER=checkupauto-staging-web
IMPORT_RECEIPT="$ROOT/migration-last-import.json"

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
if [ -e "$IMPORT_RECEIPT" ] || [ -L "$IMPORT_RECEIPT" ]; then
  echo "HOSTINGER_MIGRATION_IMPORT_RECEIPT_EXISTS"
  exit 67
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
import_result="$(python3 "$tool" import \
  --snapshot "$snapshot" \
  --target-root "$STATE" \
  --uid 10001 \
  --gid 10001)"
MIGRATION_IMPORT_RESULT="$import_result" python3 - "$IMPORT_RECEIPT" <<'PY'
import json
import os
from pathlib import Path
import re
import tempfile

target=Path(os.sys.argv[1])
payload=json.loads(os.environ["MIGRATION_IMPORT_RESULT"])
previous=str(payload.get("previousState") or "")
freeze=str(payload.get("sourceFreezeCreatedAt") or "")
if (
    payload.get("ok") is not True
    or payload.get("state")!="imported_frozen"
    or re.fullmatch(r"\.migration-previous-[0-9a-f]{32}",previous) is None
    or not freeze
):
    raise SystemExit("migration import result invalid")
receipt={
    "schemaVersion":1,
    "purpose":"hostinger-migration-import-rollback",
    "previousState":previous,
    "sourceFreezeCreatedAt":freeze,
    "fileCount":int(payload.get("fileCount") or 0),
    "sqliteCount":int(payload.get("sqliteCount") or 0),
}
raw=(json.dumps(receipt,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
fd,name=tempfile.mkstemp(prefix=".migration-last-import.",dir=str(target.parent))
temp=Path(name)
try:
    with os.fdopen(fd,"wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    temp.chmod(0o600)
    if target.exists() or target.is_symlink():
        raise SystemExit("migration import receipt appeared concurrently")
    os.replace(temp,target)
finally:
    temp.unlink(missing_ok=True)
PY
printf '%s\n' "$import_result"

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
