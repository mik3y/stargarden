"""Lighting render loop: theme (with crossfades) × master fade, then overlays → DMX.

An overlay (e.g. a lightning strike) rewrites the per-cell frames for as long
as it is active; the engine drops it once `finished`.
"""

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..config import LightingConfig
from .color import RGB, mix
from .drivers import DmxDriver
from .fixtures import CellKind, CellState, FixtureFrame, Patch
from .themes import Theme

log = logging.getLogger(__name__)


class Overlay(Protocol):
    def apply(self, frames: list[FixtureFrame], patch: Patch, t: float) -> None: ...

    def finished(self, t: float) -> bool: ...


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
        self._overlays: list[Overlay] = []
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

    def add_overlay(self, overlay: Overlay) -> None:
        self._overlays.append(overlay)

    def now(self) -> float:
        return self._clock()

    # -- rendering ------------------------------------------------------------

    @staticmethod
    def _blackout(fixture) -> FixtureFrame:
        return {cell.name: CellState(intensity=0.0) for cell in fixture.mode.cells}

    def frame(self, t: float) -> list[FixtureFrame]:
        master = self._master.at(t)
        blend = self._theme_fade.at(t) if self._theme_fade else 1.0
        if blend >= 1.0:
            self._prev_theme, self._theme_fade = None, None
        count = len(self.patch.fixtures)
        frames = []
        for i, fixture in enumerate(self.patch.fixtures):
            frame: FixtureFrame = {}
            for cell in fixture.mode.cells:
                if cell.kind is CellKind.WHITE:
                    frame[cell.name] = CellState(intensity=0.0)  # whites belong to overlays (lightning)
                else:
                    index = i + cell.position[0] - 0.5  # cells spread the neighbor-to-neighbor drift across the fixture
                    frame[cell.name] = CellState(self._color(index, count, t, blend), self._intensity(index, count, t, blend) * master)
            frames.append(frame)
        self._overlays = [o for o in self._overlays if not o.finished(t)]
        for overlay in self._overlays:
            overlay.apply(frames, self.patch, t)
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

    async def run(self) -> None:
        period = 1.0 / self.cfg.fps
        self.driver.open()
        log.info("lighting: %d fixture(s) via %s at %.0f fps", len(self.patch), self.driver.name, self.cfg.fps)
        try:
            next_frame = self._clock()
            while True:
                self.driver.send(self.patch.render(self.frame(self._clock())))
                next_frame += period
                await asyncio.sleep(max(0.0, next_frame - self._clock()))
        finally:
            self.driver.send(self.patch.render([self._blackout(f) for f in self.patch.fixtures]))
            self.driver.close()
