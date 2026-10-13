#!/usr/bin/env bash
# Create a dedicated, unencrypted SSH key for noninteractive TestFlight deploys.
# Only the public key is emitted. The private key stays in the runner's HOME.
set -euo pipefail

key_dir="${1:?expected absolute runner-owned .ssh directory}"
if [[ "$key_dir" != /* || -L "$key_dir" ]]; then
  echo "::error::Unsafe SSH key directory" >&2
  exit 2
fi

umask 077
mkdir -p -- "$key_dir"
chmod 700 -- "$key_dir"
key="$key_dir/checkupauto_macmini_ed25519"

if [[ -L "$key" || -L "$key.pub" ]]; then
  echo "::error::SSH key files must not be symlinks" >&2
  exit 2
fi

if [[ ! -e "$key" ]]; then
  if [[ -e "$key.pub" ]]; then
    echo "::error::Orphan SSH public key: manual reconciliation required" >&2
    exit 2
  fi
  ssh-keygen -q -t ed25519 -N '' -C "checkupauto-testflight-thor" -f "$key"
  echo "::notice::Dedicated TestFlight SSH key generated on runner"
fi

if [[ ! -f "$key" ]]; then
  echo "::error::Private SSH identity is not a regular file" >&2
  exit 2
fi

chmod 600 -- "$key"
public="$(ssh-keygen -y -P '' -f "$key" 2>/dev/null)" || {
  echo "::error::Runner SSH key is invalid or passphrase-protected" >&2
  exit 2
}
if [[ ! "$public" =~ ^ssh-ed25519[[:space:]] ]]; then
  echo "::error::Unexpected runner SSH key format" >&2
  exit 2
fi
printf '%s\n' "$public" > "$key.pub"
chmod 644 -- "$key.pub"

fingerprint="$(ssh-keygen -l -E sha256 -f "$key.pub" | awk '{print $2}')"
printf 'MAC_MINI_SSH_PUBLIC_FINGERPRINT=%s\n' "$fingerprint"
# Public keys are intended for distribution to the Mac mini, unlike private keys.
printf 'MAC_MINI_SSH_PUBLIC_KEY=%s\n' "$public"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    printf '%s\n' '### TestFlight runner SSH authorization'
    printf '%s\n' 'Authorize this **public** key in /Users/tarek/.ssh/authorized_keys on the Mac mini:'
    printf '\x60\x60\x60text\n'
    printf '%s\n' "$public"
    printf '\x60\x60\x60\n'
    printf '%s\n' 'The private key remains on the Linux runner and is never printed or transferred.'
  } >> "$GITHUB_STEP_SUMMARY"
fi
