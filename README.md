# Stargarden

Stargarden is a Python program that runs the sound and lighting program for "Stargarden", an art installation.

Stargarden is a secluded spot in a nighttime forest, featuring a comfy platform for lying down, looking up at the stars, and taking in the atmosphere.

As a visitor approaches Stargarden, they see trees encircling the platform which are uplighted with various multi-color DMX fixtures, slowly and even subtly changing against a coherent color theme. Ambient background forest sounds play on a sound system in the background, which encircles the space. Occasionally, a discrete sound (like a bird flapping or calling) is also played over the ambient selection, this sound taking advantage of the quad-channel sound output to make it appear to come from a specific space, or move around the space.

Unbeknownst to the visitor, upon their arrival, a bluetooth motion sensor has fired and determined that the space is occupied. After a set amount of time (e.g. 10 minutes), something happens: The lights fade off briefly, and a new sound takes over: a musical track from a privately curated playlist of chill, beautiful tunes. The lighting program gets slightly more active and matches the music.

As the track ends, the "normal" program returns. So long as presence is detected in the space, the program repeats after another delay, with a new track.

## Design

### States

The program, and the art itself, has the following major states:

* `OFF`: All lighting and sound disabled. The daytime state.
* `AMBIENT`: Ambient forest sounds and lighting; the default nighttime mode of operation.
* `PRESENCE`: The space is occupied. Ambient programming continues, and a countdown to the next show begins.
* `SHOW`: The music program. Lights fade off briefly, then a track from the curated playlist plays with a more active, music-matched lighting theme. On track end, the program returns to `PRESENCE` (restarting the countdown) or `AMBIENT` if the space has been vacated.

Transitions:

* `OFF ↔ AMBIENT`: driven by the sunset/sunrise scheduler, or manually from the console.
* `AMBIENT → PRESENCE`: presence detector reports occupied.
* `PRESENCE → SHOW`: occupancy has persisted for `show_delay` (default 10 minutes; subsequent shows use `show_repeat_delay`).
* `PRESENCE → AMBIENT`: presence detector reports the space definitively vacated.
* Any state can be forced manually from the console; a manual state pins until released.

### Architecture decisions

* **Single asyncio process.** One Python process hosts all components; the TUI is just another component and can be disabled (`--headless`) when running under systemd. Audio rendering runs in the PortAudio callback thread; everything else is async tasks.
* **Lighting is pure Python.** No external lighting desk. The looks we need — slow generative color drift, theme palettes, music-mode intensity, occasional lightning — are simple math over a handful of fixtures, and keeping them in-process keeps lighting locked to program state and audio events. We define our own small fixture profiles.
* **DMX out via Enttec Open DMX USB.** The widget is a bare FTDI UART with no DMX engine, so we generate the signal ourselves: a transmitter thread streams the latest universe back to back over `pyserial` at 250 kbaud 8N2, producing each frame's break and mark-after-break with the port's break line. The render loop just swaps in new frames at ~30 Hz, and the wire stays alive (holding the last look) even if the loop stalls. The driver is behind a small interface; the DMX USB Pro (which has its own engine and takes snapshots over its framed protocol) is also supported, and other adapters (or sACN) can be added later.
* **Audio via `sounddevice` (PortAudio) with our own mixer.** A numpy mixing engine renders N layers → per-layer gain → 4-speaker panning, at 48 kHz float32. Quad mode maps FL/FR/RL/RR to outputs 1–4 of a class-compliant USB interface; stereo mode (developer MacBooks) folds the rear channels down with attenuation so spatial effects remain audible.
* **Presence via `bleak` passive BLE scanning.** Two Shelly Blu Motion sensors (platform + walkway) broadcasting **unencrypted** BTHome v2 advertisements; no pairing, no bindkeys. Encryption support can be added later if needed.
* **TUI via Textual.** Logs, state display/override, per-layer volume and lighting peak, and (in dev) simulated fixtures and motion injection.
* **Scheduling via `astral`.** Sunset/sunrise computed from configured lat/long drives `OFF ↔ AMBIENT`.
* **Config is TOML** (`stdlib tomllib`): a program config plus an assets manifest.
* **Fully offline in the field.** No network dependency at runtime. Deploys happen by visiting the Pi (rsync over direct link/hotspot). Because the sunset schedule depends on wall-clock time, the production Pi should carry an RTC module (e.g. DS3231); `fake-hwclock` alone drifts across power-offs.

## Major Components

### Conductor

The state machine described above. Owns timers (`show_delay`, `show_repeat_delay`), consumes presence and scheduler events, and issues coordinated commands to the audio and lighting engines (e.g. "fade lights out, then start track X with theme Y").

### Audio engine

Drives a single PortAudio output stream and mixes three layers:

* **Bed**: looping ambient forest recordings. Beds are ordinary stereo files; the engine spreads them across the quad field (decorrelated front/rear with slow drift). Bed changes crossfade.
* **Discretes**: mono one-shot sounds (bird calls, wing flaps) fired on a randomized schedule, each given a position or a motion trajectory and rendered with equal-power panning across the four speakers. Preloaded into memory.
* **Music**: the show track. While music plays, the bed ducks to a configured low level (the forest never fully disappears) and discretes are suppressed; both return when the track ends.

Files are decoded with `soundfile` (WAV/FLAC/OGG/MP3). Beds and music are streamed from disk by a decode thread feeding ring buffers, so the audio callback never touches the filesystem. Per-layer gain is adjustable live from the console; overall peak volume is managed by the external amplifier.

### Lighting engine

A 30 Hz render loop composes, per fixture, a base **theme** (slow color drift within a palette, per-fixture phase offsets so the trees don't move in unison), scaled by the program's master fade and a standing **peak** ceiling (`lighting.peak`, default 1.0; nudged live from the console for softer light on real fixtures), with optional **overlays** (lightning strobe, show-mode intensity) applied on top and exempt from the peak, then writes the universe to the DMX driver.

* **Fixture types** with their **DMX modes** (built in: `generic` washes, the ADJ Jolt Bar FX2) and the **patch** (fixture → type, mode, DMX address) are declared in config. A mode exposes **cells** — the fixture's light-emitting sub-units with positions — and channels carrying GDTF-named attributes; the engine sets per-cell state and the renderer resolves shared (master) dimmers and strobes. Vocabulary: `docs/lighting-concepts.md`.
* **Themes** are small Python classes registered by name, sampled per cell at a `Spot` (fixture, grid column and row). Ambient mode runs one program, `ember-waves`: waves of amber and orange travelling along the bars, every other column dark. Show themes are selected per the music manifest.
* **Overlays** rewrite the per-cell frames on top of the theme while active; lightning is the first.
* Drivers: `enttec_open` (Enttec Open DMX USB), `enttec_pro` (Enttec DMX USB Pro), `console` (virtual fixture swatches in the TUI), `null`.

### Lightning

A layer of its own, independent of the themes (`lightning.py`). Strikes arrive at random — about one per `mean_interval_s` (20 minutes by default), never closer than `min_interval_s`, and only in the configured program states (`PRESENCE` by default, so an empty forest stays calm). Each strike is composed fresh from the RNG:

* an **origin**: one of the fixtures, never the same tree twice in a row;
* an optional faint **leader** flicker, then 1–3 **primary** flashes at the origin (40–120 ms, white cells at full, sometimes with the hardware strobe engaged for crackle);
* a **ripple**: every other fixture repeats each flash later and dimmer with distance (fixtures without white cells push their color toward white instead), then a short afterglow at the origin;
* **thunder** after 0.3–2.5 s, one of the manifest's `[[thunder]]` sounds (never the same one twice in a row), louder for short delays, panned to the origin and rolling slightly toward the center of the space.

Sound and light land in the same place because fixtures and speakers share one coordinate space: fixture `position` and `audio.speakers` are both points on the compass square (x −1 left … 1 right, y −1 rear … 1 front). Speaker positions default to the four corners in output order; swapping cables means swapping two entries.

### Presence detection

A passive BLE scanner parses BTHome v2 advertisements from the two Shelly Blu Motion sensors and feeds a latching occupancy model:

* Motion at the **platform** sensor ⇒ occupied immediately.
* Occupancy is held while *any* sensor reports motion within `vacancy_timeout` (default 15 minutes) — a still, stargazing visitor won't retrigger PIR constantly, so absence of events is not evidence of absence until the timeout lapses.
* The **walkway** sensor refreshes the hold and marks likely arrival; available to future heuristics (e.g. pre-warming, distinguishing pass-throughs).

Sensor MAC addresses are configured; sensors must have BLE encryption disabled in the Shelly app.

### Scheduler

Computes today's dusk/dawn from configured coordinates and requests `OFF ↔ AMBIENT` transitions, with configurable offsets (e.g. lights from 20 min after sunset until 30 min before sunrise). Manual console overrides always win.

### TUI console

A Textual app showing recent log lines, current state and timers, presence sensor status, and per-layer volume sliders. Allows forcing/releasing states. In simulation mode it additionally renders virtual fixture color swatches and offers keys to inject platform/walkway motion events.

## Hardware

Production target:

* Raspberry Pi (Raspberry Pi OS), with RTC module for offline timekeeping
* Enttec Open DMX USB (a DMX USB Pro also works, with `driver = "enttec_pro"`)
* Class-compliant USB audio interface with ≥4 outputs, into external amplification (4 speakers encircling the space)
* 4× ADJ Jolt Bar FX2, one per corner, addressed back to back from 1 (38 channels each: 1, 39, 77, 115). The type is built in with all 17 of its DMX modes (`type = "jolt_bar_fx2"`, `mode = "38ch"`…); we run it in **38CH**: 4 RGB columns rendered as a gradient, and the white LEDs as their own cells with a separate dimmer and strobe, which is what lightning flashes. Reference material for it lives in `docs/fixtures/`. Generic RGB/RGBW washes are also supported (`type = "generic"`).
* 2× Shelly Blu Motion (platform, walkway), unencrypted BTHome broadcasts

Development target: macOS laptop, no hardware — stereo audio out, simulated fixtures and sensors.

## Configuration & assets

`config.toml` holds machine/site specifics: audio device, channel mode and speaker positions, DMX driver and serial port, fixture patch, sensor MACs, lat/long and schedule offsets, timers, duck levels, lightning odds.

Audio assets live **outside the repo** in a configurable assets directory (deployed via rsync; the repo carries only tiny test sounds for development):

```
assets/
  manifest.toml     # beds, discrete pools (weights, spatial behavior), music playlist
  beds/             # stereo ambience loops
  discretes/        # mono one-shots
  discretes/thunder/  # thunder for lightning strikes
  music/            # curated show tracks
```

Each music playlist entry may name a specific show lighting theme; otherwise one is chosen at random from the show-theme pool.

## Development

```
uv sync                                   # Python 3.14 + deps into .venv
uv run python scripts/make_test_assets.py # synthesize stand-in sounds into assets-dev/
uv run stargarden                         # console UI with configs/dev.toml
uv run stargarden --headless              # logs to stderr instead of the console
uv run pytest
```

The dev config selects stereo output (falling back to a silent clock if PortAudio
is missing), DMX out through an Enttec Open DMX USB if one is plugged in (the
console shows virtual fixtures regardless; set `driver = "console"` to skip the
hardware entirely), simulated presence, and a schedule override so it is always
"night". Console keys:

| key | action |
|---|---|
| `m` / `w` | fake platform / walkway motion |
| `0` `1` `2` `3` | force OFF / AMBIENT / PRESENCE / SHOW |
| `r` | release the forced state |
| `n` | toggle day/night override |
| `l` / `s` | trigger a lightning strike / a discrete sound |
| `d` | toggle DEBUG-level logging in the log pane |
| `tab`, `[`, `]` | select an audio layer or the lighting peak, nudge it |
| `q` | quit |

Show timers are seconds in `configs/dev.toml` (`show_delay_s = 45`), so a full
visit can be watched in a couple of minutes: press `m`, wait, and the lights
drop out before a track starts.

### Code layout

```
src/stargarden/
  __init__.py     CLI entry point (`stargarden`)
  app.py          runtime wiring: transitions → audio/lighting commands
  conductor.py    the OFF/AMBIENT/PRESENCE/SHOW state machine
  config.py       config.toml → dataclasses
  manifest.py     assets/manifest.toml → beds, discretes, music
  scheduler.py    sunset/sunrise via astral
  lightning.py    strike composition, scheduling, thunder
  presence/       occupancy model, BTHome parser, bleak scanner
  lighting/       fixtures & patch, themes, render engine, DMX drivers
  audio/          decoders, quad panner, streaming sources, mixer, backends, engine
  tui/            Textual console
configs/          dev.toml (simulation) and production.toml (Pi template)
docs/             lighting-concepts.md (vocabulary appendix), fixtures/ (reference files)
scripts/          make_test_assets.py
tests/            pytest; `test_app.py` runs a whole simulated visit
```

Fixture types live in `lighting/fixtures.py` (see `docs/lighting-concepts.md`
for the vocabulary). A simple one-cell fixture can also be declared in config as
a list of channel roles under `[lighting.profiles.<name>]` (`red`, `green`,
`blue`, `white`, `dimmer`, `dimmer_fine`, `strobe`; anything else is parked at 0)
and patched with `type = "<name>"`.

Pure logic (state machine, occupancy, panning, themes, patch rendering) takes an
injected clock and is unit-tested; hardware adapters (`sounddevice`, `bleak`,
`pyserial`) are imported lazily so a machine without them still runs in
simulation.

## Deployment

On the Pi: `uv sync`, copy `configs/production.toml` to the site config and fill
in coordinates, sensor MACs, the DMX patch, and the audio device; rsync the
assets directory to `assets.root`; run `stargarden --config <site>.toml
--headless` from a systemd unit (`Restart=always`). Fit an RTC module so the
sunset schedule survives power cycles offline.

The Open DMX USB appears as a plain FTDI serial port (`ftdi_sio`, no extra
driver); the service user needs to be in the `dialout` group, and
`lighting.port = "auto"` finds it (pin `/dev/serial/by-id/usb-ENTTEC_...` if
several FTDI devices are attached). A widget that is missing or unplugged is
logged once and retried every couple of seconds, so the rest of the program
keeps running.

## Open questions

* Exact USB audio interface model for the Pi (any class-compliant 4-out should do; to be validated).
* Theme design itself — palettes, drift behavior, show looks — will be iterated with the fixtures in hand.
* Whether the walkway sensor should trigger any audible/visible "greeting" on approach.
