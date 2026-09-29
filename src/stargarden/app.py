"""Runtime wiring: builds every component from config and translates
conductor transitions into audio and lighting commands."""

import asyncio
import logging
import random
from collections.abc import Coroutine, Iterable

from .audio import AudioEngine, Layer
from .audio.tempo import TempoAnalyzer, TempoCache
from .check import SetupCheck
from .conductor import Conductor, State
from .config import Config, ConfigError, SensorRole
from .lighting import LightingEngine, Patch
from .lighting.drivers import make_driver
from .lighting.themes import AMBIENT_THEMES, SHOW_THEMES, Theme, get_theme, pick_ambient, pick_show
from .lightning import Lightning
from .manifest import Manifest, MusicEntry
from .presence import OccupancyModel
from .scheduler import SunSchedule
from .state import Overrides, StateStore

log = logging.getLogger(__name__)

CONDUCTOR_TICK_S = 0.2
SCHEDULE_POLL_S = 15.0


class Stargarden:
    def __init__(self, config: Config, manifest: Manifest, seed: int | None = None) -> None:
        self.config = config
        self.manifest = manifest
        self.rng = random.Random(seed)
        self.conductor = Conductor(config.timers)
        self.occupancy = OccupancyModel(config.presence.vacancy_timeout_s)
        self.schedule = SunSchedule(config.site, config.schedule)
        self.night_override: bool | None = None
        self.store = StateStore(config.state.path)
        self.overrides: Overrides = self.store.load()
        self._save_handle: asyncio.TimerHandle | None = None
        self.patch = Patch.from_config(config.lighting)
        first = pick_ambient(self.rng, enabled=self.enabled_themes(AMBIENT_THEMES))
        self.lighting = LightingEngine(self.patch, make_driver(config.lighting), config.lighting, first, self.rng)
        self.audio = AudioEngine(config.audio, config.discretes, manifest, self.rng, self._track_finished_from_audio_thread)
        self.tempo = TempoAnalyzer(manifest, TempoCache(config.state.path.with_name("bpm.json"), config.assets_root))
        for name, level in self.overrides.levels.items():
            if name in Layer.__members__.values():
                self.audio.set_level(Layer(name), level)
        if self.overrides.peak is not None:
            self.lighting.set_peak(self.overrides.peak)
        unknown = set(config.lightning.states) - {s.value for s in State}
        if unknown:
            raise ConfigError(f"lightning.states: unknown states {sorted(unknown)}")
        self.lightning = Lightning(
            config.lightning, self.patch, self.lighting, self.audio, manifest, self.rng, allowed=self.lightning_allowed
        )
        self.check = SetupCheck(self.conductor, self.lighting, self.audio, self.patch)
        self.ambient_theme: Theme = self.lighting.theme
        self.show_theme: Theme | None = None
        self.last_music: MusicEntry | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._show_task: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []
        self.conductor.add_listener(self._on_transition)

    # -- console inputs -------------------------------------------------------

    def simulate_motion(self, role: SensorRole) -> None:
        log.info("sim: %s motion", role)
        self.occupancy.motion(role)
        self.conductor.set_occupied(self.occupancy.occupied)

    def set_night_override(self, night: bool | None) -> None:
        self.night_override = night
        self.conductor.set_night(self._is_night())

    def lightning_allowed(self) -> bool:
        return self.conductor.state.value in self.config.lightning.states

    def _is_night(self) -> bool:
        return self.schedule.is_night() if self.night_override is None else self.night_override

    # -- lifecycle ------------------------------------------------------------

    def background_tasks(self) -> list:
        coros = [
            self.lighting.run(),
            self.audio.run(),
            self.lightning.run(),
            self._conductor_loop(),
            self._schedule_loop(),
            self._ambient_theme_loop(),
        ]
        if self.config.presence.source == "ble":
            from .presence.ble import BlePresenceSource

            coros.append(BlePresenceSource(self.occupancy, self.config.presence.sensors).run())
        return coros

    async def run(self, foreground=None, background: Iterable[Coroutine] = ()) -> None:
        """Run all components plus any extra `background` coroutines (e.g. the web console);
        if `foreground` (e.g. the TUI) is given, stop when it returns."""
        self._loop = asyncio.get_running_loop()
        self.audio.start()
        self.tempo.start()  # tracks not yet in the cache get their tempo measured in the background
        try:
            async with asyncio.TaskGroup() as tg:
                self._tasks = [tg.create_task(coro) for coro in (*self.background_tasks(), *background)]
                if foreground is not None:
                    await foreground
                    self.shutdown()
        finally:
            self.tempo.stop()
            self.audio.stop()
            if self._save_handle is not None:  # a change still waiting for its debounce
                self._save_handle.cancel()
                self._save_state()

    def shutdown(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._show_task:
            self._show_task.cancel()
        self.check.stop()

    async def _conductor_loop(self) -> None:
        while True:
            self.conductor.set_occupied(self.occupancy.occupied)
            self.conductor.tick()
            await asyncio.sleep(CONDUCTOR_TICK_S)

    async def _schedule_loop(self) -> None:
        while True:
            self.conductor.set_night(self._is_night())
            await asyncio.sleep(SCHEDULE_POLL_S)

    async def _ambient_theme_loop(self) -> None:
        while True:
            await asyncio.sleep(self.config.timers.ambient_theme_rotation_s)
            if self.conductor.state in (State.AMBIENT, State.PRESENCE):
                self.ambient_theme = self._pick_ambient()
                self.lighting.set_theme(self.ambient_theme, fade_s=60.0)

    # -- console settings that persist: levels, peak, program choices ----------

    SAVE_DELAY_S = 1.0  # level nudges come in bursts; write once they settle

    def set_level(self, layer: Layer, level: float) -> None:
        self.audio.set_level(layer, level)
        self.overrides.levels[layer.value] = self.audio.level(layer)
        self._touch_state()

    def set_peak(self, peak: float) -> None:
        self.lighting.set_peak(peak)
        self.overrides.peak = self.lighting.peak
        self._touch_state()

    def enabled_themes(self, pool: dict[str, Theme]) -> list[str]:
        return [name for name in pool if name not in self.overrides.disabled_themes]

    def set_theme_enabled(self, name: str, enabled: bool) -> None:
        """Put a program into the random rotation or take it out; at least one per pool stays in."""
        if name in AMBIENT_THEMES:
            kind, pool = "ambient", AMBIENT_THEMES
        elif name in SHOW_THEMES:
            kind, pool = "show", SHOW_THEMES
        else:
            raise ValueError(f"unknown program {name!r}")
        if not enabled and all(n == name for n in self.enabled_themes(pool)):
            raise ValueError(f"at least one {kind} program must stay enabled")
        if enabled:
            self.overrides.disabled_themes.discard(name)
        else:
            self.overrides.disabled_themes.add(name)
        log.info("programs: %s %s", name, "enabled" if enabled else "disabled")
        self._touch_state()
        if not enabled and pool is AMBIENT_THEMES and self.ambient_theme.name == name:
            self.ambient_theme = self._pick_ambient()  # a show in progress keeps its theme until it ends
            if self.conductor.state in (State.AMBIENT, State.PRESENCE):
                self.lighting.set_theme(self.ambient_theme, fade_s=6.0)

    def set_theme(self, name: str, fade_s: float = 3.0) -> Theme:
        """Play a program now, whatever the rotation would have picked."""
        try:
            theme = get_theme(name)
        except KeyError:
            raise ValueError(f"unknown program {name!r}") from None
        if name in AMBIENT_THEMES:
            self.ambient_theme = theme
        elif name in SHOW_THEMES:
            self.show_theme = theme
        self.lighting.set_theme(theme, fade_s=fade_s)
        return theme

    def reset_overrides(self) -> None:
        """Back to the config file: levels, peak, and every program in the rotation."""
        levels = self.config.audio.levels
        for layer, level in ((Layer.BED, levels.bed), (Layer.DISCRETES, levels.discretes), (Layer.MUSIC, levels.music)):
            self.audio.set_level(layer, level)
        self.lighting.set_peak(self.config.lighting.peak)
        self.overrides = Overrides()
        log.info("state: reset to the config defaults")
        self._touch_state()

    def _pick_ambient(self) -> Theme:
        return pick_ambient(self.rng, avoid=self.ambient_theme, enabled=self.enabled_themes(AMBIENT_THEMES))

    def _pick_show(self) -> Theme:
        return pick_show(self.rng, avoid=self.show_theme, enabled=self.enabled_themes(SHOW_THEMES))

    def _touch_state(self) -> None:
        if self._loop is None or not self._loop.is_running():
            self._save_state()
        elif self._save_handle is None:
            self._save_handle = self._loop.call_later(self.SAVE_DELAY_S, self._save_state)

    def _save_state(self) -> None:
        self._save_handle = None
        try:
            self.store.save(self.overrides)
        except OSError as e:
            log.warning("state: could not write %s: %s", self.store.path, e)

    def next_theme(self, fade_s: float = 3.0) -> Theme:
        """Step to the next lighting program in the current mode's pool, in the pool's
        fixed order: a deterministic walk for trying them by hand, unlike the random
        rotation. During a show it steps the show pool; otherwise the ambient one, and
        the choice holds until the rotation next moves on."""
        showing = self.conductor.state is State.SHOW
        pool = list((SHOW_THEMES if showing else AMBIENT_THEMES).values())
        current = self.lighting.theme
        theme = pool[(pool.index(current) + 1) % len(pool)] if current in pool else pool[0]
        if theme is current:
            log.info("lighting: %s is the only %s theme", theme.name, "show" if showing else "ambient")
            return theme
        if showing:
            self.show_theme = theme
        else:
            self.ambient_theme = theme
        self.lighting.set_theme(theme, fade_s=fade_s)
        return theme

    # -- transitions ----------------------------------------------------------

    def _on_transition(self, old: State, new: State) -> None:
        if old is State.SHOW and self._show_task and not self._show_task.done():
            self._show_task.cancel()
        if new is State.OFF:
            self.audio.stop_music(fade_s=3.0)
            self.audio.stop_ambient(fade_s=6.0)
            self.lighting.fade_master(0.0, 6.0)
            return
        if old is State.OFF:
            self.audio.start_ambient()
            self.lighting.set_theme(self.ambient_theme)
            self.lighting.fade_master(1.0, 8.0)
        if new is State.SHOW:
            self._show_task = asyncio.get_running_loop().create_task(self._run_show())
        elif old is State.SHOW:
            self.audio.stop_music(fade_s=2.0)  # no-op if the track played out
            self.lighting.set_tempo(None)
            self.lighting.set_theme(self.ambient_theme, fade_s=6.0)
            self.lighting.fade_master(1.0, 3.0)

    async def _run_show(self) -> None:
        track = self.manifest.pick_music(self.rng, avoid=self.last_music)
        if track is None:
            log.warning("show: no music in manifest; skipping")
            self.conductor.track_finished()
            return
        try:
            theme = get_theme(track.theme) if track.theme else self._pick_show()
        except KeyError:
            log.warning("show: %s names unknown theme %r; picking from the pool", track.title, track.theme)
            theme = self._pick_show()
        log.info("show: %s with theme %s", track.title, theme.name)
        lights_out = self.config.timers.lights_out_s
        self.lighting.fade_master(0.0, lights_out)
        await asyncio.sleep(lights_out + 1.0)
        self.last_music = track
        self.show_theme = theme
        bpm = self.tempo.bpm_for(track)  # asked now, not earlier: the analyzer may have got to it during the blackout
        if bpm is None:
            log.info("show: %s has no tempo yet; %s runs at its own", track.title, theme.name)
        self.audio.play_music(track)
        self.lighting.set_tempo(bpm)
        self.lighting.set_theme(theme)
        self.lighting.fade_master(1.0, 4.0)

    def _track_finished_from_audio_thread(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self.conductor.track_finished)
