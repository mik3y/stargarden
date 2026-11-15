# Stargarden: sunset

Python program that holds four DMX light bars in a permanent sunset.

This branch repurposes Stargarden, the forest sound and light installation on `main`, for an event space. It keeps the lighting core and the web console. Audio, presence detection, lightning, the sunrise schedule and the terminal console are gone.

## What it does

All four bars show one color. That color drifts from a bright orange through red and magenta to a deep purple, dimming on the way, and then drifts back. The trip from orange to purple takes 15 minutes by default, and the trip back takes the same. Nothing ever jumps or goes black.

The program starts the sunset as soon as it launches and runs until it is stopped. There is no schedule.

## Controls

The web console is one page, sized for a phone.

* **The strip.** A handle sits on a strip running orange to purple. Dragging it moves the sunset and holds it there.
* **Brighter and darker.** Each press steps the sunset 5% toward orange or purple and holds it there.
* **Hold and resume.** Hold freezes the sunset where it is. Resume lets it run on from that place, in the direction it was heading.
* **Restart from orange.** Runs the sunset from the start.
* **Lights.** Fades the bars out or back up over three seconds. The sunset keeps its place while the lights are off.
* **Orange to purple.** Minutes for one leg, as presets or a typed value. Changing it never moves the sunset.
* **Brightness.** A ceiling on the whole look.
* **Purple end.** How bright the purple end is relative to the orange end, 35% by default and never below 5%.
* **Setup check.** Walks the bars in patch order with dim red, green, blue and white across each bar's columns. A bar lighting out of turn has the wrong DMX address. Red marks the bar's left end.
* **Reset to defaults.** Puts back the config file's length and levels and sets the sunset running.

A manual move glides to its new place over a few seconds instead of cutting.

The length, both levels and a held place persist across restarts and power cuts. They live in a small JSON file (`[state] path`, default `~/.local/state/stargarden/state.json`) outside the code directory, so deploys leave it alone. A running sunset starts from orange after a restart. The lights always come back on.

Every control is a plain HTTP action, so `curl` works too.

```
curl -X POST localhost:7710/api/actions/set_position -d '{"position": 0.8}'
curl -X POST localhost:7710/api/actions/set_paused -d '{"paused": false}'
curl -X POST localhost:7710/api/actions/set_leg -d '{"seconds": 1800}'
curl -X POST localhost:7710/api/actions/set_on -d '{"on": false}'
```

## Tuning the look

The colors are the `STOPS` table at the top of `src/stargarden/sunset.py`. Each stop is a place from 0 to 1 and an RGB color, and the program blends between neighbors. Edit the table and deploy to change the palette. Brightness falls in a straight line from full at the orange end to the purple-end level.

## Design

* **Single asyncio process.** A 30 Hz render loop asks the sunset for its color and level, scales it by the on/off fade and the brightness ceiling, and writes the universe to the DMX driver.
* **The sunset is a small clock** (`sunset.py`). It tracks a phase from 0 to 2, where 0 to 1 is the way out and 1 to 2 the way back. Holding, resuming and changing the length rebase the phase, so the place never jumps.
* **DMX out via Enttec Open DMX USB.** The widget is a bare FTDI UART, so a transmitter thread generates the DMX signal over `pyserial` and keeps the wire alive if the render loop stalls. The DMX USB Pro is also supported (`driver = "enttec_pro"`).
* **Fixtures.** Four ADJ Jolt Bar FX2 in 38CH mode, addressed back to back from 1 (1, 39, 77, 115). The white LEDs stay dark. Fixture types and the patch are described in `docs/lighting-concepts.md`.
* **Web console via aiohttp + React** (`web/`, built with bun, vite and Material UI). The program serves the built app, a small JSON API and a WebSocket stream. There is no login, so the Pi's network must stay private.
* **Config is TOML.** `configs/production.toml` is the Pi's config and `configs/dev.toml` is a one-minute sunset for a laptop.

API:

```
GET  /api/status             the status snapshot
GET  /api/fixtures           the fixture preview
GET  /api/log?since=N        retained log lines numbered N and up
POST /api/actions/<name>     run a console action; the JSON body holds its keyword arguments
GET  /ws                     stream of status, fixture and log messages
```

Actions are the `@action` methods on `Console` in `console.py`.

## Development

```
uv sync                                   # Python 3.14 + deps into .venv
uv run stargarden                         # runs configs/dev.toml, logs to stderr
uv run pytest

cd web && bun install && bun run build    # the web console, served at http://127.0.0.1:7710/
```

The dev config sends DMX through an Enttec Open DMX USB if one is plugged in. Without one the program logs that once, keeps retrying, and the console's fixture preview still shows the look. Set `driver = "console"` to skip the hardware entirely.

While working on the web console, `bun start` runs vite on :7711 with hot reload and proxies `/api` and `/ws` to a program on :7710. `bun run typecheck` and `bun run lint` (biome) check it.

```
src/stargarden/
  __init__.py     CLI entry point (`stargarden`)
  app.py          runtime wiring, and the console's changes persisted
  sunset.py       the palette and the there-and-back clock
  config.py       config.toml → dataclasses
  state.py        the persisted overrides file
  check.py        the setup check
  console.py      what the console shows and may do
  web.py          the console's server
  lighting/       fixtures & patch, render engine, DMX drivers
web/              the web console
configs/          dev.toml and production.toml
deploy/           Pi setup scripts and systemd units
```

## Deployment

The `justfile` drives a Pi over ssh; `just` lists the recipes. The host is `stargarden` (`just host=other deploy`, or `STARGARDEN_HOST`), and the username and key come from `~/.ssh/config`. The Pi needs a network connection for the first `prep` (apt, uv, Python) and none afterwards.

```
just prep      # a fresh Pi: packages, uv + Python 3.14, groups, the boot service; then a deploy
just deploy    # build web/, rsync the code, uv sync on the Pi, restart if running
just attach    # the program's log stream in its screen session (detach with C-a d)
just status | logs | start | stop | restart | ssh
```

A Pi that last ran `main` needs only `just deploy` from this branch. `uv sync` on the Pi needs a network the first time, because the lock file changed. The old state file is read. Its brightness peak carries over and the forest settings in it are ignored.

The code lands in `~/stargarden` with `web/dist` built on the laptop, since the Pi has no node. The web console is then at `http://<pi>/` (an nftables rule, `deploy/port80.nft`, sends port 80 to 7710).

The service (`deploy/stargarden.service`) runs the program inside a detached `screen` session owned by the ssh user. systemd restarts it if the program exits. It stops with SIGINT, which blacks the bars out on the way down.

In the field the Pi makes its own network. `stargarden-wifi.service` (`deploy/wifi-watch.sh`) watches the Wi-Fi. After 60 seconds without a connection it raises an access point, SSID `stargarden`, password `star4321`, with the Pi at `10.42.0.1`. Join it from a phone and open `http://10.42.0.1/`.

The Open DMX USB appears as a plain FTDI serial port. The service user needs to be in the `dialout` group, and `lighting.port = "auto"` finds the widget.
