"""Lighting render loop: theme (with crossfades) × master fade × peak, then overlays → DMX.

The master is the program's fade (up in ambient, out for shows and at close);
the peak is a standing ceiling on how bright the themes get, for softer light
on real fixtures. An overlay (e.g. a lightning strike) rewrites the per-cell
frames for as long as it is active, on top of both; the engine drops it once
`finished`.

Each theme is sampled on its own clock. A theme written at a tempo
(`Theme.tempo_bpm`) runs at `tempo / tempo_bpm` speed while a tempo is set
(the show track's, see `audio/tempo.py`); the rest run at 1×. The clock is
rebased whenever the rate changes, so the theme never jumps.
"""

import asyncio
import logging
import math
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..config import LightingConfig
from .color import RGB, mix
from .drivers import DmxDriver
from .fixtures import CellKind, CellState, FixtureFrame, Patch
from .themes import Spot, Theme

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


@dataclass
class _ThemeClock:
    """A theme's time as a function of the engine's: continuous across rate changes."""

    origin: float  # engine time at the last rebase
    theme_origin: float  # theme time then
    rate: float = 1.0

    def at(self, t: float) -> float:
        return self.theme_origin + (t - self.origin) * self.rate

    def rebased(self, t: float, rate: float) -> _ThemeClock:
        return _ThemeClock(t, self.at(t), rate)


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
        self.tempo: float | None = None  # the show track's BPM while one plays
        self._time = _ThemeClock(0.0, 0.0)
        self._prev_theme: Theme | None = None
        self._prev_time = self._time
        self._theme_fade: _Ramp | None = None
        self._master = _Ramp(0.0, 0.0, 0.0, 0.0)
        self.peak = cfg.peak
        self._overlays: list[Overlay] = []
        self.last_frames: list[FixtureFrame] = [self._blackout(f) for f in patch.fixtures]
        self._spots: list[dict[str, Spot]] = self._spots_for(patch)

    # -- control --------------------------------------------------------------

    def set_theme(self, theme: Theme, fade_s: float = 0.0) -> None:
        if theme is self.theme:
            return
        log.info("lighting: theme %s (fade %.0fs)", theme.name, fade_s)
        now = self._clock()
        self._prev_theme, self._prev_time = self.theme, self._time
        self.theme = theme
        self._time = _ThemeClock(now, now, self._rate(theme))
        self._theme_fade = _Ramp(0.0, 1.0, now, fade_s)

    def set_tempo(self, bpm: float | None) -> None:
        """Run tempo-written themes at `bpm` (None: at their own tempo); takes effect without a jump."""
        if bpm is not None and bpm <= 0:
            raise ValueError(f"tempo must be positive, got {bpm}")
        if bpm == self.tempo:
            return
        self.tempo = bpm
        now = self._clock()
        self._time = self._time.rebased(now, self._rate(self.theme))
        if self._prev_theme is not None:
            self._prev_time = self._prev_time.rebased(now, self._rate(self._prev_theme))
        if bpm is not None:
            log.info("lighting: tempo %.1f bpm (%s at %.2fx)", bpm, self.theme.name, self._time.rate)
        else:
            log.info("lighting: tempo released")

    def theme_time(self, t: float) -> float:
        """The current theme's own time at engine time `t`."""
        return self._time.at(t)

    def _rate(self, theme: Theme) -> float:
        if self.tempo is None or theme.tempo_bpm is None:
            return 1.0
        return self.tempo / theme.tempo_bpm

    def fade_master(self, target: float, seconds: float) -> None:
        now = self._clock()
        self._master = _Ramp(self._master.at(now), target, now, seconds)

    def master(self) -> float:
        return self._master.at(self._clock())

    def set_peak(self, peak: float) -> None:
        self.peak = min(1.0, max(0.0, peak))
        log.info("lighting: peak %.2f", self.peak)

    def nudge_peak(self, delta: float) -> float:
        self.set_peak(self.peak + delta)
        return self.peak

    def add_overlay(self, overlay: Overlay) -> None:
        self._overlays.append(overlay)

    def now(self) -> float:
        return self._clock()

    # -- rendering ------------------------------------------------------------

    @staticmethod
    def _blackout(fixture) -> FixtureFrame:
        return {cell.name: CellState(intensity=0.0) for cell in fixture.mode.cells}

    @staticmethod
    def _spots_for(patch: Patch) -> list[dict[str, Spot]]:
        """A Spot per color cell: its place on the fixture's grid of distinct column and row
        positions, and its place on the ring of columns running clockwise around the space
        (fixtures by the bearing of their position from the center, columns left to right)."""
        grids = []
        for fixture in patch.fixtures:
            cells = fixture.mode.color_cells
            xs = sorted({c.position[0] for c in cells})
            ys = sorted({c.position[1] for c in cells})
            grids.append((xs, ys))
        count = len(patch.fixtures)
        bearing = [math.atan2(f.position[0], f.position[1]) % (2 * math.pi) for f in patch.fixtures]  # clockwise from north
        order = sorted(range(count), key=lambda i: (bearing[i], i))
        ring_count = sum(len(xs) for xs, _ in grids)
        ring_base = {}
        offset = 0
        for i in order:
            ring_base[i] = offset
            offset += len(grids[i][0])
        spots = []
        for i, fixture in enumerate(patch.fixtures):
            xs, ys = grids[i]
            spots.append(
                {
                    c.name: Spot(
                        i,
                        count,
                        xs.index(c.position[0]),
                        len(xs),
                        ys.index(c.position[1]),
                        len(ys),
                        ring_base[i] + xs.index(c.position[0]),
                        ring_count,
                    )
                    for c in fixture.mode.color_cells
                }
            )
        return spots

    def frame(self, t: float) -> list[FixtureFrame]:
        level = self._master.at(t) * self.peak
        blend = self._theme_fade.at(t) if self._theme_fade else 1.0
        if blend >= 1.0:
            self._prev_theme, self._theme_fade = None, None
        frames = []
        for fixture, spots in zip(self.patch.fixtures, self._spots, strict=True):
            frame: FixtureFrame = {}
            for cell in fixture.mode.cells:
                if cell.kind is CellKind.WHITE:
                    frame[cell.name] = CellState(intensity=0.0)  # whites belong to overlays (lightning)
                else:
                    spot = spots[cell.name]
                    frame[cell.name] = CellState(self._color(spot, t, blend), self._intensity(spot, t, blend) * level)
            frames.append(frame)
        self._overlays = [o for o in self._overlays if not o.finished(t)]
        for overlay in self._overlays:
            overlay.apply(frames, self.patch, t)
        self.last_frames = frames
        return frames

    def _color(self, spot: Spot, t: float, blend: float) -> RGB:
        rgb = self.theme.color(spot, self._time.at(t))
        if self._prev_theme is not None and blend < 1.0:
            return mix(self._prev_theme.color(spot, self._prev_time.at(t)), rgb, blend)
        return rgb

    def _intensity(self, spot: Spot, t: float, blend: float) -> float:
        value = self.theme.intensity(spot, self._time.at(t))
        if self._prev_theme is not None and blend < 1.0:
            prev = self._prev_theme.intensity(spot, self._prev_time.at(t))
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
