#!/usr/bin/env bash
# Prepares this Raspberry Pi to run Stargarden at boot, inside a screen session
# (with port 80 forwarded to the web console, and a fallback Wi-Fi access
# point for when the site has no network),
# owned by the user running this script (`screen -r stargarden` to watch the
# console). Run by `just prep` after the code has been rsync'd to ~/stargarden.
# Idempotent: rerun it whenever it changes. Assumes Raspberry Pi OS with
# passwordless sudo for this user (the default) and a network connection, for
# apt and for uv's download of Python 3.14 and the packages.
set -euo pipefail

code="$HOME/stargarden"
packages=(screen rsync libportaudio2 libsndfile1 bluez iw dnsmasq-base nftables)
groups=(dialout audio bluetooth plugdev)  # DMX serial port, audio device, BLE scanner, USB
AP=stargarden-ap  # the fallback access point (deploy/wifi-watch.sh raises it)
AP_SSID=${AP_SSID:-stargarden}
AP_PSK=${AP_PSK:-star4321}
AP_ADDRESS=10.42.0.1/24

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

echo "== fallback access point"
sudo rfkill unblock wifi bluetooth
wifi=$(nmcli -t -f DEVICE,TYPE device status | awk -F: '$2 == "wifi" { print $1; exit }')
if [[ -z "$wifi" ]]; then
    echo "no wifi device; skipping"
elif nmcli -t -f NAME con show | grep -qx "$AP"; then
    sudo nmcli con modify "$AP" ssid "$AP_SSID" wifi-sec.psk "$AP_PSK" ipv4.addresses "$AP_ADDRESS"
    echo "profile $AP updated"
else
    sudo nmcli con add type wifi ifname "$wifi" con-name "$AP" autoconnect no ssid "$AP_SSID" \
        802-11-wireless.mode ap 802-11-wireless.band bg ipv4.method shared ipv4.addresses "$AP_ADDRESS" \
        wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$AP_PSK" >/dev/null
    echo "profile $AP created: ssid $AP_SSID at ${AP_ADDRESS%/*}"
fi

echo "== services"
deploy/install-services.sh >/dev/null
sudo systemctl enable stargarden stargarden-wifi stargarden-port80
sudo systemctl restart stargarden stargarden-wifi stargarden-port80
sleep 2
systemctl --no-pager status stargarden | head -5

echo
echo "done. \`screen -r stargarden\` (or \`just attach\`) shows the log; the web console is at http://$(hostname)/ (port 80 -> 7710)."
echo "with no wifi for 60s the Pi raises its own network: ssid $AP_SSID, console at http://${AP_ADDRESS%/*}/."
echo "fill in configs/production.toml (coordinates, sensor MACs) on the laptop and \`just deploy\`."
