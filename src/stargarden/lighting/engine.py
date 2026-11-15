"""Lighting render loop: the look × master fade × peak, then overlays → DMX.

The look is one color and brightness for every color cell of every fixture.
The master is the on/off fade; the peak is a standing ceiling on brightness.
An overlay (the setup check) rewrites the per-cell frames for as long as it is
active, on top of both; the engine drops it once `finished`.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..config import LightingConfig
from .color import RGB
from .drivers import DmxDriver
from .fixtures import CellKind, CellState, Fixture, FixtureFrame, Patch

log = logging.getLogger(__name__)

Look = Callable[[], tuple[RGB, float]]  # the color and brightness to show now


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
        look: Look,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.patch = patch
        self.driver = driver
        self.cfg = cfg
        self.look = look
        self._clock = clock
        self._master = _Ramp(0.0, 0.0, 0.0, 0.0)
        self.peak = cfg.peak
        self._overlays: list[Overlay] = []
        self.last_frames: list[FixtureFrame] = [self._blackout(f) for f in patch.fixtures]

    def fade_master(self, target: float, seconds: float) -> None:
        """Fade everything the look shows to `target` (0 dark, 1 full)."""
        now = self._clock()
        self._master = _Ramp(self._master.at(now), target, now, seconds)

    def master(self) -> float:
        """The master fade's level now."""
        return self._master.at(self._clock())

    def set_peak(self, peak: float) -> None:
        """Set the ceiling on the look's brightness."""
        self.peak = min(1.0, max(0.0, peak))
        log.info("lighting: peak %.2f", self.peak)

    def add_overlay(self, overlay: Overlay) -> None:
        self._overlays.append(overlay)

    @staticmethod
    def _blackout(fixture: Fixture) -> FixtureFrame:
        return {cell.name: CellState(intensity=0.0) for cell in fixture.mode.cells}

    def frame(self, t: float) -> list[FixtureFrame]:
        color, intensity = self.look()
        level = intensity * self._master.at(t) * self.peak
        frames = []
        for fixture in self.patch.fixtures:
            frame: FixtureFrame = {}
            for cell in fixture.mode.cells:
                if cell.kind is CellKind.WHITE:
                    frame[cell.name] = CellState(intensity=0.0)  # the sunset has no white in it
                else:
                    frame[cell.name] = CellState(color, level)
            frames.append(frame)
        self._overlays = [o for o in self._overlays if not o.finished(t)]
        for overlay in self._overlays:
            overlay.apply(frames, self.patch, t)
        self.last_frames = frames
        return frames

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
