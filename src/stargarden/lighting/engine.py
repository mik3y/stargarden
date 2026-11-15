"""Lighting render loop: the program × master fade × peak, then overlays → DMX.

A program says what color and brightness each cell of the bars shows at a
beat. The sunset is one program and the dance patterns are the others, and a
change of program crossfades. The engine counts beats at its tempo, so a tempo
change speeds a pattern up or slows it without a jump. The master is the on/off
fade; the peak is a standing ceiling on the bars' brightness.

Pin spots do not show the program. They hold one color, white or the
program's accent, at a level of their own under the master.

An overlay (the setup check) rewrites the per-cell frames for as long as it is
active, on top of everything; the engine drops it once `finished`.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..config import MAX_TEMPO_BPM, MIN_TEMPO_BPM, FixtureRole, LightingConfig, SpotColor
from .color import RGB, mix
from .drivers import DmxDriver
from .fixtures import CellKind, CellState, Fixture, FixtureFrame, Patch

log = logging.getLogger(__name__)

WHITE: RGB = (1.0, 1.0, 1.0)


@dataclass(frozen=True)
class Spot:
    """Where a program is sampled: bar `bar` of `bars`, at (col of cols, row of rows) in its grid of cells."""

    bar: int
    bars: int
    col: int = 0
    cols: int = 1
    row: int = 0
    rows: int = 1

    @property
    def column(self) -> int:
        """The column's place along all the bars laid end to end in patch order."""
        return self.bar * self.cols + self.col

    @property
    def columns(self) -> int:
        """How many columns the bars have between them."""
        return self.bars * self.cols


class Program(Protocol):
    name: str

    def cell(self, spot: Spot, beat: float) -> tuple[RGB, float]:
        """The color and brightness of one cell."""
        ...

    def accent(self, beat: float) -> RGB:
        """The one color that stands for the look, for the pin spots."""
        ...


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
        program: Program,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.patch = patch
        self.driver = driver
        self.cfg = cfg
        self.program = program
        self._prev_program: Program | None = None
        self._program_fade: _Ramp | None = None
        self._clock = clock
        self._master = _Ramp(0.0, 0.0, 0.0, 0.0)
        self.peak = cfg.peak
        self.tempo = cfg.tempo_bpm
        self.spot_level = cfg.spot_level
        self.spot_color = cfg.spot_color
        self._beat = 0.0
        self._beat_at = clock()
        self._overlays: list[Overlay] = []
        self.last_frames: list[FixtureFrame] = [self._blackout(f) for f in patch.fixtures]
        self._spots = self._spots_for(patch)

    def set_program(self, program: Program, fade_s: float = 0.0) -> None:
        """Show another program, crossfading from the current one."""
        if program is self.program:
            return
        log.info("lighting: program %s (fade %.0fs)", program.name, fade_s)
        self._prev_program = self.program
        self.program = program
        self._program_fade = _Ramp(0.0, 1.0, self._clock(), fade_s)

    def fade_master(self, target: float, seconds: float) -> None:
        """Fade everything but overlays to `target` (0 dark, 1 full)."""
        now = self._clock()
        self._master = _Ramp(self._master.at(now), target, now, seconds)

    def master(self) -> float:
        """The master fade's level now."""
        return self._master.at(self._clock())

    def set_peak(self, peak: float) -> None:
        """Set the ceiling on the bars' brightness."""
        self.peak = min(1.0, max(0.0, peak))
        log.info("lighting: peak %.2f", self.peak)

    def set_tempo(self, bpm: float) -> None:
        """Set the dance patterns' pace, without moving them."""
        if not MIN_TEMPO_BPM <= bpm <= MAX_TEMPO_BPM:
            raise ValueError(f"tempo must be {MIN_TEMPO_BPM:g} to {MAX_TEMPO_BPM:g} bpm")
        self.beat(self._clock())
        self.tempo = float(bpm)

    def set_spot_level(self, level: float) -> None:
        """Set the pin spots' brightness."""
        self.spot_level = min(1.0, max(0.0, level))

    def beat(self, t: float) -> float:
        """Beats counted so far, at whatever tempos were in force."""
        self._beat += max(0.0, t - self._beat_at) * self.tempo / 60.0
        self._beat_at = t
        return self._beat

    def add_overlay(self, overlay: Overlay) -> None:
        self._overlays.append(overlay)

    @staticmethod
    def _blackout(fixture: Fixture) -> FixtureFrame:
        return {cell.name: CellState(intensity=0.0) for cell in fixture.mode.cells}

    @staticmethod
    def _spots_for(patch: Patch) -> list[dict[str, Spot]]:
        """A Spot per color cell of each bar, from the cells' distinct column and row positions; none for pin spots."""
        bars = [f for f in patch.fixtures if f.role is FixtureRole.BAR]
        spots = []
        for fixture in patch.fixtures:
            if fixture.role is not FixtureRole.BAR:
                spots.append({})
                continue
            cells = fixture.mode.color_cells
            xs = sorted({c.position[0] for c in cells})
            ys = sorted({c.position[1] for c in cells})
            bar = bars.index(fixture)
            spots.append({c.name: Spot(bar, len(bars), xs.index(c.position[0]), len(xs), ys.index(c.position[1]), len(ys)) for c in cells})
        return spots

    def frame(self, t: float) -> list[FixtureFrame]:
        beat = self.beat(t)
        master = self._master.at(t)
        blend = self._program_fade.at(t) if self._program_fade else 1.0
        if blend >= 1.0:
            self._prev_program, self._program_fade = None, None
        accent = WHITE if self.spot_color is SpotColor.WHITE else self._accent(beat, blend)
        frames = []
        for fixture, spots in zip(self.patch.fixtures, self._spots, strict=True):
            frame: FixtureFrame = {}
            for cell in fixture.mode.cells:
                if cell.kind is CellKind.WHITE:
                    frame[cell.name] = CellState(intensity=0.0)  # no program uses the bars' white LEDs
                elif fixture.role is FixtureRole.SPOT:
                    frame[cell.name] = CellState(accent, self.spot_level * master)
                else:
                    color, intensity = self._cell(spots[cell.name], beat, blend)
                    frame[cell.name] = CellState(color, intensity * master * self.peak)
            frames.append(frame)
        self._overlays = [o for o in self._overlays if not o.finished(t)]
        for overlay in self._overlays:
            overlay.apply(frames, self.patch, t)
        self.last_frames = frames
        return frames

    def _cell(self, spot: Spot, beat: float, blend: float) -> tuple[RGB, float]:
        """One cell of the program, crossfaded from the previous program while a change is under way."""
        color, intensity = self.program.cell(spot, beat)
        if self._prev_program is None:
            return color, intensity
        was_color, was_intensity = self._prev_program.cell(spot, beat)
        # weight the colors by brightness, so a dark cell's color does not tint the fade
        lit = was_intensity * (1.0 - blend) + intensity * blend
        share = intensity * blend / lit if lit > 0 else blend
        return mix(was_color, color, share), lit

    def _accent(self, beat: float, blend: float) -> RGB:
        """The program's accent, crossfaded like its cells."""
        accent = self.program.accent(beat)
        if self._prev_program is None:
            return accent
        return mix(self._prev_program.accent(beat), accent, blend)

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
