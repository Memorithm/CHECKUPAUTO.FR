#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly GROUP="cybercheck-deploy"
readonly HELPER_SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cybercheck-deploy"
readonly HELPER_TARGET="/usr/local/sbin/cybercheck-deploy"
readonly SUDOERS_TARGET="/etc/sudoers.d/cybercheck-deploy"

fail() {
  printf '[install-deploy-helper] ERROR: %s\n' "$*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "root privileges are required"
[[ "$#" -eq 1 ]] || fail "usage: install-deploy-helper.sh <deployment-user>"
readonly DEPLOY_USER="$1"
[[ "$DEPLOY_USER" =~ ^[a-z_][a-z0-9_-]*[$]?$ ]] || fail "invalid deployment user name"
getent passwd "$DEPLOY_USER" >/dev/null || fail "deployment user does not exist"
[[ -f "$HELPER_SOURCE" ]] || fail "deploy helper source is missing"
command -v visudo >/dev/null || fail "visudo is required"

getent group "$GROUP" >/dev/null || groupadd --system "$GROUP"
usermod -a -G "$GROUP" "$DEPLOY_USER"
install -o root -g root -m 0755 "$HELPER_SOURCE" "$HELPER_TARGET"

readonly TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
cat >"$TMP" <<EOF
# CheckupAuto production deployment: only the root-owned, argument-validating helper.
%${GROUP} ALL=(root) NOPASSWD: ${HELPER_TARGET} *
EOF
visudo -cf "$TMP" >/dev/null
install -o root -g root -m 0440 "$TMP" "$SUDOERS_TARGET"
visudo -cf "$SUDOERS_TARGET" >/dev/null

printf 'Installed %s and %s.\n' "$HELPER_TARGET" "$SUDOERS_TARGET"
printf 'User %s is now in group %s; restart its login/service session before first use.\n' "$DEPLOY_USER" "$GROUP"
