#!/usr/bin/env bash
# Prepares this Raspberry Pi to run Stargarden at boot, inside a screen session
# owned by the user running this script (`screen -r stargarden` to watch the
# console). Run by `just prep` after the code has been rsync'd to ~/stargarden.
# Idempotent: rerun it whenever it changes. Assumes Raspberry Pi OS with
# passwordless sudo for this user (the default) and a network connection, for
# apt and for uv's download of Python 3.14 and the packages.
set -euo pipefail

code="$HOME/stargarden"
unit=/etc/systemd/system/stargarden.service
packages=(screen rsync libportaudio2 libsndfile1 bluez)
groups=(dialout audio bluetooth plugdev)  # DMX serial port, audio device, BLE scanner, USB

cd "$code"

echo "== packages"
missing=()
for p in "${packages[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
done
if ((${#missing[@]})); then
    sudo apt-get update -q
    sudo apt-get install -y --no-install-recommends "${missing[@]}"
else
    echo "all present"
fi

echo "== uv"
export PATH="$HOME/.local/bin:$PATH"
if [ ! -x "$HOME/.local/bin/uv" ]; then  # the lock needs a current uv, not whatever apt has
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv --version

echo "== python and packages"
uv sync --frozen --no-dev

echo "== groups for $USER"
for g in "${groups[@]}"; do
    if getent group "$g" >/dev/null && ! id -nG "$USER" | tr ' ' '\n' | grep -qx "$g"; then
        sudo usermod -aG "$g" "$USER"
        echo "added to $g"
    fi
done

echo "== service"
sed -e "s|@USER@|$USER|g" -e "s|@HOME@|$HOME|g" deploy/stargarden.service | sudo tee "$unit" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable stargarden
sudo systemctl restart stargarden
sleep 2
systemctl --no-pager status stargarden | head -5

echo
echo "done. \`screen -r stargarden\` (or \`just attach\`) shows the console; the web console is on :7710."
echo "fill in configs/production.toml (coordinates, sensor MACs) on the laptop and \`just deploy\`."
