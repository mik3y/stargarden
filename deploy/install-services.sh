#!/usr/bin/env bash
# Renders deploy/*.service for this user and installs the ones that changed,
# printing their names (one per line) so the caller can restart them. Used by
# prep.sh and update.sh.
set -euo pipefail

cd "$(dirname "$0")"
changed=()
for src in *.service; do
    unit=/etc/systemd/system/$src
    rendered=$(sed -e "s|@USER@|$USER|g" -e "s|@HOME@|$HOME|g" "$src")
    if [[ ! -f "$unit" ]] || ! diff -q <(echo "$rendered") "$unit" >/dev/null; then
        echo "$rendered" | sudo tee "$unit" >/dev/null
        changed+=("${src%.service}")
    fi
done
if ((${#changed[@]})); then
    sudo systemctl daemon-reload
    printf '%s\n' "${changed[@]}"
fi
