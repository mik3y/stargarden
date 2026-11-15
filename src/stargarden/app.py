"""Runtime wiring: builds the sunset and the lighting engine from config, and
keeps the console's changes across runs."""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine, Iterable

from .check import SetupCheck
from .config import Config
from .lighting import LightingEngine, Patch
from .lighting.drivers import make_driver
from .state import Overrides, StateStore
from .sunset import Sunset

log = logging.getLogger(__name__)

FADE_S = 3.0  # lights on and off


class Stargarden:
    SAVE_DELAY_S = 1.0  # slider moves come in bursts; write once they settle

    def __init__(self, config: Config, clock: Callable[[], float] = time.monotonic) -> None:
        self.config = config
        self.store = StateStore(config.state.path)
        self.overrides: Overrides = self.store.load()
        self.sunset = Sunset(config.sunset.leg_s, config.sunset.dusk_level, clock)
        self.patch = Patch.from_config(config.lighting)
        self.lighting = LightingEngine(self.patch, make_driver(config.lighting), config.lighting, self.sunset.look, clock)
        self.check = SetupCheck(self.lighting, self.patch)
        self.on = True
        self._save_handle: asyncio.TimerHandle | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tasks: list[asyncio.Task] = []
        self._apply_overrides()

    def _apply_overrides(self) -> None:
        """Put the saved console settings over the config's; one that no longer fits is dropped."""
        o = self.overrides
        try:
            if o.leg_s is not None:
                self.sunset.set_leg(o.leg_s)
            if o.dusk_level is not None:
                self.sunset.set_dusk_level(o.dusk_level)
        except ValueError as e:
            log.warning("state: ignoring %s: %s", self.store.path, e)
            self.overrides = o = Overrides()
        if o.peak is not None:
            self.lighting.set_peak(o.peak)
        if o.hold is not None:
            self.sunset.seek(o.hold)
        self.sunset.snap()

    async def run(self, foreground: Coroutine | None = None, background: Iterable[Coroutine] = ()) -> None:
        """Run the lights plus any extra `background` coroutines (the web console);
        if `foreground` is given, stop when it returns."""
        self._loop = asyncio.get_running_loop()
        self.lighting.fade_master(1.0 if self.on else 0.0, FADE_S)
        try:
            async with asyncio.TaskGroup() as tg:
                self._tasks = [tg.create_task(coro) for coro in (self.lighting.run(), *background)]
                if foreground is not None:
                    await foreground
                    self.shutdown()
        finally:
            if self._save_handle is not None:  # a change still waiting for its debounce
                self._save_handle.cancel()
                self._save_state()

    def shutdown(self) -> None:
        """Stop `run`."""
        for task in self._tasks:
            task.cancel()
        self.check.stop()

    def set_on(self, on: bool) -> None:
        """Fade the lights up or out; the sunset keeps its place and keeps running either way."""
        self.on = on
        self.lighting.fade_master(1.0 if on else 0.0, FADE_S)
        log.info("lights: %s", "on" if on else "off")

    def seek(self, position: float) -> float:
        """Hold the sunset at a place until resumed."""
        position = self.sunset.seek(position)
        self.overrides.hold = position
        log.info("sunset: held at %.0f%%", position * 100)
        self._touch_state()
        return position

    def set_paused(self, paused: bool) -> None:
        """Hold the sunset where it is, or let it run on from there."""
        if paused:
            self.sunset.pause()
            self.overrides.hold = self.sunset.position
        else:
            self.sunset.resume()
            self.overrides.hold = None
        log.info("sunset: %s %.0f%%", "held at" if paused else "running from", self.sunset.position * 100)
        self._touch_state()

    def restart(self) -> None:
        """Run the sunset from the orange end."""
        self.sunset.restart()
        self.overrides.hold = None
        log.info("sunset: restarted")
        self._touch_state()

    def set_leg(self, seconds: float) -> float:
        """Change how long orange to purple takes; a value equal to the config's drops the override."""
        self.sunset.set_leg(seconds)
        self.overrides.leg_s = None if self.sunset.leg_s == self.config.sunset.leg_s else self.sunset.leg_s
        log.info("sunset: %.0fs from orange to purple", self.sunset.leg_s)
        self._touch_state()
        return self.sunset.leg_s

    def set_dusk_level(self, level: float) -> float:
        """Change the brightness of the purple end."""
        self.sunset.set_dusk_level(level)
        self.overrides.dusk_level = self.sunset.dusk_level
        self._touch_state()
        return self.sunset.dusk_level

    def set_peak(self, peak: float) -> float:
        """Change the ceiling on brightness."""
        self.lighting.set_peak(peak)
        self.overrides.peak = self.lighting.peak
        self._touch_state()
        return self.lighting.peak

    def reset_overrides(self) -> None:
        """Back to the config file's length, dusk level and peak, with the sunset running."""
        self.overrides = Overrides()
        self.sunset.set_leg(self.config.sunset.leg_s)
        self.sunset.set_dusk_level(self.config.sunset.dusk_level)
        self.sunset.resume()
        self.lighting.set_peak(self.config.lighting.peak)
        log.info("state: reset to the config defaults")
        self._touch_state()

    def _touch_state(self) -> None:
        """Save the overrides soon, or now when no loop is running."""
        if self._loop is None or not self._loop.is_running():
            self._save_state()
        elif self._save_handle is None:
            self._save_handle = self._loop.call_later(self.SAVE_DELAY_S, self._save_state)

    def _save_state(self) -> None:
        """Write the overrides file."""
        self._save_handle = None
        try:
            self.store.save(self.overrides)
        except OSError as e:
            log.warning("state: could not write %s: %s", self.store.path, e)
