#!/usr/bin/env bash
# Keeps the Pi reachable in the field. When it has had no Wi-Fi for GRACE_S it
# raises its own access point (the NetworkManager profile prep.sh creates, SSID
# "stargarden" by default, 10.42.0.1) so a laptop can join it and reach the web
# console. While the access point is up and nobody is connected to it, the known
# networks are tried again every RETRY_S; with someone on it, it stays up.
# Runs as root under stargarden-wifi.service; logs to the journal.
set -euo pipefail

AP=${AP:-stargarden-ap}  # the connection profile's name
GRACE_S=${GRACE_S:-60}
RETRY_S=${RETRY_S:-600}
POLL_S=${POLL_S:-10}

log() { echo "$*"; }

wifi_dev() { nmcli -t -f DEVICE,TYPE device status | awk -F: '$2 == "wifi" { print $1; exit }'; }
active_con() { nmcli -t -f GENERAL.CONNECTION device show "$1" 2>/dev/null | cut -d: -f2-; }
connected() { nmcli -t -f GENERAL.STATE device show "$1" 2>/dev/null | grep -q ':100 '; }  # 100 (connected)
clients() { iw dev "$1" station dump 2>/dev/null | grep -c '^Station' || true; }

down_since=""
ap_since=""
while true; do
    now=$(date +%s)
    dev=$(wifi_dev)
    if [[ -z "$dev" ]]; then
        sleep "$POLL_S"
        continue
    fi
    con=$(active_con "$dev")
    if [[ "$con" == "$AP" ]]; then
        if (( $(clients "$dev") == 0 )) && (( now - ap_since >= RETRY_S )); then
            log "nobody on the access point; trying the known networks"
            nmcli con down "$AP" >/dev/null || true
            waited=0
            while (( waited < GRACE_S )); do  # NetworkManager autoconnects whatever it knows
                sleep 5; waited=$((waited + 5))
                if connected "$dev" && [[ "$(active_con "$dev")" != "$AP" ]]; then break; fi
            done
            if connected "$dev" && [[ "$(active_con "$dev")" != "$AP" ]]; then
                log "back on $(active_con "$dev")"
                down_since=""; ap_since=""
            else
                log "still no wifi; access point back up"
                nmcli con up "$AP" >/dev/null || log "could not raise $AP"
                ap_since=$(date +%s)
            fi
        fi
    elif connected "$dev" && [[ -n "$con" ]]; then
        if [[ -n "$down_since" ]]; then log "wifi up: $con"; fi
        down_since=""
    else
        down_since=${down_since:-$now}
        if (( now - down_since >= GRACE_S )); then
            log "no wifi for ${GRACE_S}s; raising the access point $AP"
            if nmcli con up "$AP" >/dev/null; then
                ap_since=$(date +%s)
            else
                log "could not raise $AP; will retry"
            fi
            down_since=$(date +%s)
        fi
    fi
    sleep "$POLL_S"
done
