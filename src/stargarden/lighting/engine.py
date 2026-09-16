"""Lighting render loop: theme (with crossfades) × master fade × overlays → DMX."""

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..config import LightingConfig
from .color import RGB, mix
from .drivers import DmxDriver
from .fixtures import CellKind, CellState, FixtureFrame, Patch
from .themes import Theme

log = logging.getLogger(__name__)

LIGHTNING_COLOR = (0.85, 0.9, 1.0)


@dataclass
class _Ramp:
    start_value: float
    end_value: float
    start_t: float
    duration: float

    def at(self, t: float) -> float:
        if self.duration <= 0 or t >= self.start_t + self.duration:
            return self.end_value
        if t <= self.start_t:
            return self.start_value
        u = (t - self.start_t) / self.duration
        return self.start_value + (self.end_value - self.start_value) * u


class LightingEngine:
    def __init__(
        self,
        patch: Patch,
        driver: DmxDriver,
        cfg: LightingConfig,
        theme: Theme,
        rng: random.Random | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.patch = patch
        self.driver = driver
        self.cfg = cfg
        self._clock = clock
        self._rng = rng or random.Random()
        self.theme = theme
        self._prev_theme: Theme | None = None
        self._theme_fade: _Ramp | None = None
        self._master = _Ramp(0.0, 0.0, 0.0, 0.0)
        self._flashes: list[tuple[float, float]] = []  # (start_t, end_t)
        self._next_lightning = self._schedule_lightning(clock())
        self.last_frames: list[FixtureFrame] = [self._blackout(f) for f in patch.fixtures]

    # -- control --------------------------------------------------------------

    def set_theme(self, theme: Theme, fade_s: float = 0.0) -> None:
        if theme is self.theme:
            return
        log.info("lighting: theme %s (fade %.0fs)", theme.name, fade_s)
        now = self._clock()
        self._prev_theme = self.theme
        self.theme = theme
        self._theme_fade = _Ramp(0.0, 1.0, now, fade_s)

    def fade_master(self, target: float, seconds: float) -> None:
        now = self._clock()
        self._master = _Ramp(self._master.at(now), target, now, seconds)

    def master(self) -> float:
        return self._master.at(self._clock())

    def trigger_lightning(self) -> None:
        now = self._clock()
        t = now + 0.05
        for _ in range(self._rng.randint(2, 4)):
            duration = self._rng.uniform(0.06, 0.18)
            self._flashes.append((t, t + duration))
            t += duration + self._rng.uniform(0.05, 0.35)
        log.info("lighting: lightning")

    # -- rendering ------------------------------------------------------------

    @staticmethod
    def _blackout(fixture) -> FixtureFrame:
        return {cell.name: CellState(intensity=0.0) for cell in fixture.mode.cells}

    def frame(self, t: float) -> list[FixtureFrame]:
        master = self._master.at(t)
        blend = self._theme_fade.at(t) if self._theme_fade else 1.0
        if blend >= 1.0:
            self._prev_theme, self._theme_fade = None, None
        self._flashes = [f for f in self._flashes if f[1] > t]
        flashing = any(f[0] <= t < f[1] for f in self._flashes)
        count = len(self.patch.fixtures)
        frames = []
        for i, fixture in enumerate(self.patch.fixtures):
            mode = fixture.mode
            # lightning: pulse the white cells and let the color program carry on;
            # fixtures with no whites but a shutter flash their color cells instead
            flash_whites = flashing and bool(mode.white_cells)
            flash_color = flashing and not mode.white_cells and mode.can_flash
            frame: FixtureFrame = {}
            for cell in mode.cells:
                if cell.kind is CellKind.WHITE:
                    frame[cell.name] = CellState(intensity=1.0 if flash_whites else 0.0, strobe=1.0 if flash_whites else 0.0)
                elif flash_color:
                    frame[cell.name] = CellState(LIGHTNING_COLOR, 1.0, 1.0)
                else:
                    index = i + cell.position[0] - 0.5  # cells spread the neighbor-to-neighbor drift across the fixture
                    frame[cell.name] = CellState(self._color(index, count, t, blend), self._intensity(index, count, t, blend) * master)
            frames.append(frame)
        self.last_frames = frames
        return frames

    def _color(self, index: float, count: int, t: float, blend: float) -> RGB:
        rgb = self.theme.color(index, count, t)
        if self._prev_theme is not None and blend < 1.0:
            return mix(self._prev_theme.color(index, count, t), rgb, blend)
        return rgb

    def _intensity(self, index: float, count: int, t: float, blend: float) -> float:
        value = self.theme.intensity(index, count, t)
        if self._prev_theme is not None and blend < 1.0:
            prev = self._prev_theme.intensity(index, count, t)
            return prev + (value - prev) * blend
        return value

    def _schedule_lightning(self, now: float) -> float:
        cfg = self.cfg.lightning
        wait = max(cfg.min_interval_s, self._rng.expovariate(1.0 / max(cfg.mean_interval_s, 1.0)))
        return now + wait

    def _maybe_lightning(self, now: float) -> None:
        if now < self._next_lightning:
            return
        self._next_lightning = self._schedule_lightning(now)
        if self.cfg.lightning.enabled and self.theme.lightning_ok and self.patch.can_flash and self.master() > 0.5:
            self.trigger_lightning()

    async def run(self) -> None:
        period = 1.0 / self.cfg.fps
        self.driver.open()
        log.info("lighting: %d fixture(s) via %s at %.0f fps", len(self.patch), self.driver.name, self.cfg.fps)
        try:
            next_frame = self._clock()
            while True:
                now = self._clock()
                self._maybe_lightning(now)
                self.driver.send(self.patch.render(self.frame(now)))
                next_frame += period
                await asyncio.sleep(max(0.0, next_frame - self._clock()))
        finally:
            self.driver.send(self.patch.render([self._blackout(f) for f in self.patch.fixtures]))
            self.driver.close()
