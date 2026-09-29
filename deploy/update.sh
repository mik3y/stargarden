#!/usr/bin/env bash
# Runs on the Pi after each rsync (`just deploy`): refreshes the packages and,
# if the service is running, restarts it so the new code takes over.
set -euo pipefail

cd "$HOME/stargarden"
export PATH="$HOME/.local/bin:$PATH"

uv sync --frozen --no-dev

changed=$(deploy/install-services.sh)
if grep -qx stargarden-wifi <<<"$changed"; then
    sudo systemctl restart stargarden-wifi
    echo "restarted stargarden-wifi"
fi

if ! systemctl cat stargarden.service >/dev/null 2>&1; then
    echo "no service installed yet: run \`just prep\`"
elif systemctl is-active --quiet stargarden; then
    sudo systemctl restart stargarden
    echo "restarted stargarden"
else
    echo "stargarden is stopped, not starting it: \`just start\` when ready"
fi
