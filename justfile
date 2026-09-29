# Stargarden on the Pi: `just prep` sets up a fresh one, `just deploy` updates it.
# `just` alone lists the recipes. Override the ssh host with `just host=<name> deploy`
# (or STARGARDEN_HOST); the username and key come from ~/.ssh/config.

set shell := ["bash", "-euo", "pipefail", "-c"]

host := env_var_or_default("STARGARDEN_HOST", "stargarden")
# the audio library to ship, relative to this file (assets-dev/ is the synthesized stand-in set)
assets := env_var_or_default("STARGARDEN_ASSETS", "assets-dev")

# on the Pi, relative to the ssh user's home; production.toml's assets.root matches
remote_code := "stargarden"
remote_assets := "stargarden-assets"

# everything git ignores, except web/dist which the Pi cannot build itself
excludes := "--exclude=.git --exclude=.venv --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache --exclude=.DS_Store --exclude=assets-dev --exclude=web/node_modules"

default:
    @just --list --unsorted

# one-time setup of a fresh Pi (packages, uv, groups, boot service), then a full deploy; safe to rerun
prep: sync
    ssh -t {{host}} '~/{{remote_code}}/deploy/prep.sh'

# build the web console, push code and assets, sync packages, restart the server if it is running
deploy: sync
    ssh {{host}} '~/{{remote_code}}/deploy/update.sh'

# rsync the code (with a fresh web/dist) and the assets to the Pi
sync: web
    rsync -az --delete {{excludes}} ./ {{host}}:{{remote_code}}/
    rsync -az --delete {{assets}}/ {{host}}:{{remote_assets}}/

# build the web console into web/dist
web:
    cd web && bun install --frozen-lockfile && bun run build

# attach to the server's screen session (detach with C-a d)
attach:
    ssh -t {{host}} screen -r stargarden

# the service: start / stop / restart it, show its state
start:
    ssh {{host}} sudo systemctl start stargarden

stop:
    ssh {{host}} sudo systemctl stop stargarden

restart:
    ssh {{host}} sudo systemctl restart stargarden

status:
    ssh {{host}} 'systemctl --no-pager status stargarden || true'

# follow the service log (the TUI's log pane is the richer view: `just attach`)
logs:
    ssh -t {{host}} journalctl -u stargarden -f

# a login shell in ~/stargarden on the Pi
ssh:
    ssh -t {{host}} 'cd ~/{{remote_code}} && exec $SHELL -l'
