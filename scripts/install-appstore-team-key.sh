#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  install-appstore-team-key.sh /path/to/AuthKey_XXXXXXXXXX.p8 ISSUER_UUID

Installs an App Store Connect Team API key into the private Checkup Auto
release vault on this Mac. The Team ID is not stored here; the release
workflow derives it from the provisioning profile for fr.checkupauto.reminder.
EOF
}

[ "$#" -eq 2 ] || { usage >&2; exit 2; }

source_key="$1"
issuer_id="$2"

[ -f "$source_key" ] || {
  echo "Key file does not exist: $source_key" >&2
  exit 2
}

key_name="$(basename "$source_key")"
key_id="$(printf '%s\n' "$key_name" | sed -nE 's/^AuthKey_([A-Za-z0-9]{10})\.p8$/\1/p')"
[ -n "$key_id" ] || {
  echo "Key filename must match AuthKey_XXXXXXXXXX.p8" >&2
  exit 2
}

[[ "$issuer_id" =~ ^[0-9A-Fa-f-]{36}$ ]] || {
  echo "Issuer ID must be a 36-character UUID" >&2
  exit 2
}

first_line="$(head -1 "$source_key")"
[ "$first_line" = "-----BEGIN PRIVATE KEY-----" ] || {
  echo "The supplied file is not an App Store Connect private key" >&2
  exit 2
}

root="$HOME/Library/Application Support/CheckupAuto/AppStoreConnect"
mkdir -p "$root"
chmod 700 "$root"

existing=("$root"/AuthKey_*.p8)
if [ -e "${existing[0]}" ]; then
  for item in "${existing[@]}"; do
    [ "$(basename "$item")" = "$key_name" ] || {
      echo "Another App Store Connect key is already installed: $(basename "$item")" >&2
      exit 2
    }
  done
fi

destination="$root/$key_name"
umask 077
tmp_key="$(mktemp "$root/.key.XXXXXX")"
tmp_issuer="$(mktemp "$root/.issuer.XXXXXX")"
trap 'rm -f "$tmp_key" "$tmp_issuer"' EXIT

cat "$source_key" > "$tmp_key"
printf '%s\n' "$issuer_id" > "$tmp_issuer"
chmod 600 "$tmp_key" "$tmp_issuer"

mv -f "$tmp_key" "$destination"
mv -f "$tmp_issuer" "$root/issuer-id"
trap - EXIT

echo "CHECKUPAUTO_APPSTORE_TEAM_KEY_INSTALLED key_id=$key_id"
