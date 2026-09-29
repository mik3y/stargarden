#!/usr/bin/env bash
# Runs on the Pi after each rsync (`just deploy`): refreshes the packages and,
# if the service is running, restarts it so the new code takes over.
set -euo pipefail

cd "$HOME/stargarden"
export PATH="$HOME/.local/bin:$PATH"

uv sync --frozen --no-dev

for unit in $(deploy/install-services.sh); do  # the helper units restart on change; stargarden itself below
    if [[ "$unit" != stargarden ]]; then
        sudo systemctl restart "$unit"
        echo "restarted $unit"
    fi
done

if ! systemctl cat stargarden.service >/dev/null 2>&1; then
    echo "no service installed yet: run \`just prep\`"
elif systemctl is-active --quiet stargarden; then
    sudo systemctl restart stargarden
    echo "restarted stargarden"
else
    echo "stargarden is stopped, not starting it: \`just start\` when ready"
fi
