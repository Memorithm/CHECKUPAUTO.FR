#!/usr/bin/env bash
set -euo pipefail

ROOT="${CYBERCHECK_ROOT:-/root/CyberCheckLive}"
BASELINE="/root/CyberCheckIntegrity/integrity-baseline.json"

if [[ "${EUID}" -ne 0 ]]; then
  echo "This operation must run as root." >&2
  exit 1
fi

cd "$ROOT"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing rebaseline: working tree is not clean." >&2
  git status --short >&2
  exit 2
fi

git fetch --quiet origin main
LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse origin/main)"
if [[ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]]; then
  echo "Refusing rebaseline: local HEAD is not origin/main." >&2
  exit 3
fi
systemctl stop cybercheck.service
trap 'systemctl start cybercheck.service >/dev/null 2>&1 || true' EXIT

"$ROOT/.venv/bin/python" - <<'PY'
import json
import security_integrity as integrity
result = integrity.rebaseline()
print(json.dumps({
    'ok': result.get('ok'),
    'baselineGitHead': result.get('baselineGitHead'),
    'protectedFiles': result.get('protectedFiles'),
}, indent=2))
PY

chown root:cybercheck "$BASELINE"
chmod 0640 "$BASELINE"
systemctl start cybercheck.service
trap - EXIT

echo "Integrity baseline approved for $LOCAL_HEAD"
