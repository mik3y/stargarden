"""The sunset: a place between bright orange (0) and deep purple (1) that drifts there and back.

One leg, orange to purple, takes `leg_s`; the way back takes the same, so the
look never jumps. A console can hold the sunset at a place of its choosing and
later let it run on from there. The place the lights show follows the real one
at a limited speed, so a manual move glides instead of cutting.
"""

import math
import time
from collections.abc import Callable

from .config import MAX_LEG_S, MIN_DUSK_LEVEL, MIN_LEG_S
from .lighting.color import RGB, clamp01, mix
from .lighting.engine import Spot

STOPS: tuple[tuple[float, RGB], ...] = (
    (0.00, (1.0, 0.42, 0.02)),  # amber
    (0.25, (1.0, 0.20, 0.0)),  # orange
    (0.50, (1.0, 0.04, 0.0)),  # red
    (0.70, (0.95, 0.0, 0.22)),  # crimson
    (0.86, (0.62, 0.0, 0.62)),  # magenta
    (1.00, (0.32, 0.0, 0.78)),  # violet
)
GLIDE_S = 4.0  # how long a manual move from one end to the other takes to show
DARKENING, BRIGHTENING = "darkening", "brightening"


def color_at(position: float) -> RGB:
    """The sunset's color at a place, interpolated between the stops around it."""
    p = clamp01(position)
    for (p0, c0), (p1, c1) in zip(STOPS, STOPS[1:], strict=False):
        if p <= p1:
            return mix(c0, c1, (p - p0) / (p1 - p0))
    return STOPS[-1][1]


def level_at(position: float, dusk_level: float) -> float:
    """Brightness at a place, falling evenly from full at the orange end to `dusk_level` at the purple end."""
    return 1.0 - (1.0 - dusk_level) * clamp01(position)


class Sunset:
    name = "sunset"

    def __init__(self, leg_s: float = 900.0, dusk_level: float = 0.35, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.leg_s = leg_s
        self.dusk_level = dusk_level
        self.paused = False
        self._phase = 0.0  # 0..1 is the way out to purple, 1..2 the way back
        self._origin = clock()  # when `_phase` was true, while running
        self._shown = 0.0
        self._shown_at = self._origin

    def phase(self) -> float:
        """Where the cycle is, in legs, 0 up to 2."""
        if self.paused:
            return self._phase
        return (self._phase + (self._clock() - self._origin) / self.leg_s) % 2.0

    @property
    def position(self) -> float:
        """The sunset's place, 0 (orange) to 1 (purple)."""
        phase = self.phase()
        return phase if phase <= 1.0 else 2.0 - phase

    @property
    def direction(self) -> str:
        """Which way the sunset is heading, or would be if it were running."""
        return DARKENING if self.phase() < 1.0 else BRIGHTENING

    @property
    def leg_remaining_s(self) -> float:
        """Seconds until the sunset reaches the end it is heading for."""
        return (1.0 - self.phase() % 1.0) * self.leg_s

    def _rebase(self, phase: float) -> None:
        """Make `phase` the cycle's place as of now."""
        self._phase, self._origin = phase % 2.0, self._clock()

    def seek(self, position: float) -> float:
        """Hold the sunset at a place, keeping the way it was heading."""
        if not math.isfinite(position):
            raise ValueError("position must be a number from 0 to 1")
        position = clamp01(position)
        self._rebase(position if self.direction == DARKENING else 2.0 - position)
        self.paused = True
        return position

    def pause(self) -> None:
        """Hold the sunset where it is."""
        self._rebase(self.phase())
        self.paused = True

    def resume(self) -> None:
        """Let the sunset run on from where it is held."""
        self._rebase(self.phase())
        self.paused = False

    def restart(self) -> None:
        """Run from the orange end."""
        self._rebase(0.0)
        self.paused = False

    def set_leg(self, seconds: float) -> None:
        """Change how long orange to purple takes, without moving the sunset."""
        if not math.isfinite(seconds) or not MIN_LEG_S <= seconds <= MAX_LEG_S:
            raise ValueError(f"sunset length must be {MIN_LEG_S:g} to {MAX_LEG_S:g} seconds")
        self._rebase(self.phase())
        self.leg_s = float(seconds)

    def set_dusk_level(self, level: float) -> None:
        """Change the brightness of the purple end."""
        if not math.isfinite(level):
            raise ValueError("dusk level must be a number")
        self.dusk_level = min(1.0, max(MIN_DUSK_LEVEL, float(level)))

    def snap(self) -> None:
        """Show the sunset's place at once, skipping the glide."""
        self._shown, self._shown_at = self.position, self._clock()

    def shown(self) -> float:
        """The place the lights show, gliding toward the sunset's own."""
        now, target = self._clock(), self.position
        step = max(0.0, now - self._shown_at) / GLIDE_S
        self._shown += min(step, max(-step, target - self._shown))
        self._shown_at = now
        return self._shown

    def look(self) -> tuple[RGB, float]:
        """The color and brightness to show now."""
        position = self.shown()
        return color_at(position), level_at(position, self.dusk_level)

    def cell(self, spot: Spot, beat: float) -> tuple[RGB, float]:
        """The sunset as a lighting program, the same on every cell."""
        return self.look()

    def accent(self, beat: float) -> RGB:
        """The sunset's color now, for the pin spots."""
        return color_at(self.shown())
