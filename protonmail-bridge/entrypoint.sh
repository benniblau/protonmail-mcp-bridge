#!/usr/bin/env bash
#
# Bootstraps a passphrase-free GPG key and a `pass` store for the Proton
# Bridge keychain, then executes the bridge. All state lives under $HOME,
# which is a persisted Docker volume, so this only does real work on the
# first run — subsequent starts are no-ops and the login survives restarts.
#
set -euo pipefail

export GNUPGHOME="${GNUPGHOME:-$HOME/.gnupg}"
mkdir -p "$GNUPGHOME"
chmod 700 "$GNUPGHOME"

# 1. Passphrase-free GPG key (so pass can encrypt/decrypt without pinentry).
if ! gpg --list-secret-keys --with-colons 2>/dev/null | grep -q '^sec:'; then
    echo "[entrypoint] Generating GPG key for the bridge keychain..."
    gpg --batch --passphrase '' \
        --quick-gen-key 'ProtonMail Bridge' default default never
fi

# 2. Initialise the pass store against that key (idempotent).
if [ ! -f "$HOME/.password-store/.gpg-id" ]; then
    echo "[entrypoint] Initialising pass store..."
    key_fpr="$(gpg --list-secret-keys --with-colons | awk -F: '/^fpr:/ {print $10; exit}')"
    pass init "$key_fpr"
fi

exec "$@"
