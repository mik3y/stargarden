"""Runtime wiring: builds every component from config and translates
conductor transitions into audio and lighting commands."""

import asyncio
import logging
import random

from .audio import AudioEngine
from .conductor import Conductor, State
from .config import Config, ConfigError, SensorRole
from .lighting import LightingEngine, Patch
from .lighting.drivers import make_driver
from .lighting.themes import Theme, get_theme, pick_ambient, pick_show
from .lightning import Lightning
from .manifest import Manifest, MusicEntry
from .presence import OccupancyModel
from .scheduler import SunSchedule

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
        self.patch = Patch.from_config(config.lighting)
        self.lighting = LightingEngine(self.patch, make_driver(config.lighting), config.lighting, pick_ambient(self.rng), self.rng)
        self.audio = AudioEngine(config.audio, config.discretes, manifest, self.rng, self._track_finished_from_audio_thread)
        unknown = set(config.lightning.states) - {s.value for s in State}
        if unknown:
            raise ConfigError(f"lightning.states: unknown states {sorted(unknown)}")
        self.lightning = Lightning(
            config.lightning, self.patch, self.lighting, self.audio, manifest, self.rng, allowed=self.lightning_allowed
        )
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

    async def run(self, foreground=None) -> None:
        """Run all components; if `foreground` (e.g. the TUI) is given, stop when it returns."""
        self._loop = asyncio.get_running_loop()
        self.audio.start()
        try:
            async with asyncio.TaskGroup() as tg:
                self._tasks = [tg.create_task(coro) for coro in self.background_tasks()]
                if foreground is not None:
                    await foreground
                    self.shutdown()
        finally:
            self.audio.stop()

    def shutdown(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._show_task:
            self._show_task.cancel()

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
                self.ambient_theme = pick_ambient(self.rng, avoid=self.ambient_theme)
                self.lighting.set_theme(self.ambient_theme, fade_s=60.0)

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
            self.lighting.set_theme(self.ambient_theme, fade_s=6.0)
            self.lighting.fade_master(1.0, 3.0)

    async def _run_show(self) -> None:
        track = self.manifest.pick_music(self.rng, avoid=self.last_music)
        if track is None:
            log.warning("show: no music in manifest; skipping")
            self.conductor.track_finished()
            return
        try:
            theme = get_theme(track.theme) if track.theme else pick_show(self.rng, avoid=self.show_theme)
        except KeyError:
            log.warning("show: %s names unknown theme %r; picking from the pool", track.title, track.theme)
            theme = pick_show(self.rng, avoid=self.show_theme)
        log.info("show: %s with theme %s", track.title, theme.name)
        lights_out = self.config.timers.lights_out_s
        self.lighting.fade_master(0.0, lights_out)
        await asyncio.sleep(lights_out + 1.0)
        self.last_music = track
        self.show_theme = theme
        self.audio.play_music(track)
        self.lighting.set_theme(theme)
        self.lighting.fade_master(1.0, 4.0)

    def _track_finished_from_audio_thread(self) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self.conductor.track_finished)
