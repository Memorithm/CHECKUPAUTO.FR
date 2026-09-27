#!/usr/bin/env bash
set -euo pipefail

bundle_id="${CHECKUPAUTO_BUNDLE_ID:-fr.checkupauto.reminder}"
vault="$HOME/Library/Application Support/CheckupAuto/AppStoreConnect"

profile_teams="$(
  { find "$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"          "$HOME/Library/MobileDevice/Provisioning Profiles"          -maxdepth 1 -type f 2>/dev/null || true; } |
  while IFS= read -r profile; do
    tmp="$(mktemp)"
    if security cms -D -i "$profile" >"$tmp" 2>/dev/null; then
      app_id="$(plutil -extract Entitlements.application-identifier raw -o - "$tmp" 2>/dev/null || true)"
      if [[ "$app_id" == *."$bundle_id" ]]; then
        plutil -extract TeamIdentifier.0 raw -o - "$tmp" 2>/dev/null || true
      fi
    fi
    rm -f "$tmp"
  done |
  grep -E '^[A-Z0-9]{10}$' |
  sort -u
)"
team_count="$(printf '%s\n' "$profile_teams" | sed '/^$/d' | wc -l | tr -d ' ')"
[ "$team_count" = "1" ] || {
  echo "credential_error=provisioning_team_not_unique" >&2
  exit 2
}
team_id="$(printf '%s\n' "$profile_teams" | head -1)"

if [ ! -d "$vault" ]; then
  printf 'ready=false\nteam_id=%s\n' "$team_id"
  exit 0
fi

keys="$(
  find "$vault" -maxdepth 1 -type f -name 'AuthKey_*.p8' -print |
  sort
)"
key_count="$(printf '%s\n' "$keys" | sed '/^$/d' | wc -l | tr -d ' ')"
if [ "$key_count" = "0" ]; then
  printf 'ready=false\nteam_id=%s\n' "$team_id"
  exit 0
fi
[ "$key_count" = "1" ] || {
  echo "credential_error=app_store_key_not_unique" >&2
  exit 2
}

key_path="$(printf '%s\n' "$keys" | head -1)"
key_name="$(basename "$key_path")"
key_id="$(printf '%s\n' "$key_name" | sed -nE 's/^AuthKey_([A-Za-z0-9]{10})\.p8$/\1/p')"
[ -n "$key_id" ] || {
  echo "credential_error=key_id_invalid" >&2
  exit 2
}

issuer_file="$vault/issuer-id"
[ -f "$issuer_file" ] || {
  echo "credential_error=issuer_missing" >&2
  exit 2
}
issuer_id="$(tr -d '\r\n ' <"$issuer_file")"
[[ "$issuer_id" =~ ^[0-9A-Fa-f-]{36}$ ]] || {
  echo "credential_error=issuer_invalid" >&2
  exit 2
}

for path in "$key_path" "$issuer_file"; do
  mode="$(stat -f '%Lp' "$path")"
  case "$mode" in
    400|600) ;;
    *)
      echo "credential_error=unsafe_permissions" >&2
      exit 2
      ;;
  esac
done

first_line="$(head -1 "$key_path")"
private_key_header="-----BEGIN ""PRIVATE KEY-----"
[ "$first_line" = "$private_key_header" ] || {
  echo "credential_error=key_format_invalid" >&2
  exit 2
}

printf 'ready=true\n'
printf 'team_id=%s\n' "$team_id"
printf 'key_id=%s\n' "$key_id"
printf 'issuer_id=%s\n' "$issuer_id"
printf 'key_path=%s\n' "$key_path"
