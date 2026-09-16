"""Lighting themes: how the fixtures look over time.

A theme answers "what color and intensity is this spot at time t", where a
spot is a fixture in the patch and, for zoned fixtures, a cell of its grid.
DriftTheme walks each fixture around a palette with a per-fixture phase offset,
so the trees share a mood without moving in unison. WaveTheme, the ambient
program, sends waves of amber and orange along the bars with every other
column dark.
"""

import math
import random
from dataclasses import dataclass

from .color import RGB, mix, sample_palette


@dataclass(frozen=True)
class Spot:
    """Where a theme is sampled: fixture `fixture` of `count`, and for a zoned
    fixture the cell at (col of cols, row of rows) in its grid. `index` is the
    continuous position along the patch (fixture 2, column 5 of 16 → 2.34), so
    a bar shows a gradient of what its neighbors would show."""

    fixture: int
    count: int
    col: int = 0
    cols: int = 1
    row: int = 0
    rows: int = 1

    @property
    def index(self) -> float:
        return self.fixture + (self.col + 0.5) / self.cols - 0.5

    @property
    def void(self) -> bool:
        """Every other column of the fixture's grid, counting from the second."""
        return self.col % 2 == 1


class Theme:
    name: str

    def color(self, spot: Spot, t: float) -> RGB:
        raise NotImplementedError

    def intensity(self, spot: Spot, t: float) -> float:
        return 1.0


@dataclass(frozen=True)
class DriftTheme(Theme):
    name: str
    palette: tuple[RGB, ...]
    period_s: float = 240.0  # one fixture's trip around the palette
    spread: float = 0.23  # palette-cycle offset between neighboring fixtures
    brightness: float = 0.85
    breathe_period_s: float = 37.0
    breathe_depth: float = 0.15

    def color(self, spot: Spot, t: float) -> RGB:
        return sample_palette(self.palette, t / self.period_s + spot.index * self.spread)

    def intensity(self, spot: Spot, t: float) -> float:
        phase = t / self.breathe_period_s + spot.index * 0.37
        breathe = 0.5 + 0.5 * math.sin(2 * math.pi * phase)
        return self.brightness * (1.0 - self.breathe_depth * breathe)


@dataclass(frozen=True)
class WaveTheme(Theme):
    """Undulating waves of amber and orange.

    A wave travels along the patch (bar to bar, column to column); where it
    crests the light is bright amber, in the troughs dim deep red. A second,
    slower and longer wave runs the other way and is blended in, so the swell
    never repeats like a metronome. Over that, every other column of a bar is a
    void, nearly dark, so the up-wash breaks into separate columns with dark
    between them and the motion has something to be seen against. The voids
    slowly exchange: columns 1 and 3 hold the light for a while, cross-fade to
    columns 2 and 4, hold, and fade back. Colors stay on the red-orange-amber
    line with no blue at all, so nothing washes toward white.
    """

    name: str
    trough: RGB = (0.72, 0.03, 0.0)  # deep red
    mid: RGB = (1.0, 0.20, 0.0)  # orange
    crest: RGB = (1.0, 0.46, 0.02)  # amber
    wavelength: float = 1.4  # in fixtures; not a whole bar, so the crest slides across the columns rather than hopping
    period_s: float = 12.0  # a crest takes this long to pass one spot
    swell_wavelength: float = 2.6
    swell_period_s: float = 31.0
    swell: float = 0.35  # the slow wave's share of the blend
    sharpness: float = 1.3  # >1 narrows the crests and widens the dark between them
    trough_level: float = 0.28  # intensity in a trough, relative to a crest
    void_level: float = 0.05  # the dark columns, relative to the lit ones
    swap_period_s: float = 60.0  # one full exchange: 1/3 lit → 2/4 lit → 1/3 lit
    swap_dwell: float = 0.3  # share of the period each side holds the light; the rest is the two cross-fades
    swap_spread: float = 0.12  # cycle offset between neighboring bars, so they don't all swap at once
    brightness: float = 1.0

    def wave(self, spot: Spot, t: float) -> float:
        """0 in a trough, 1 at a crest."""
        u = spot.index
        fast = 0.5 + 0.5 * math.sin(2 * math.pi * (u / self.wavelength - t / self.period_s))
        slow = 0.5 + 0.5 * math.sin(2 * math.pi * (u / self.swell_wavelength + t / self.swell_period_s))
        return ((1.0 - self.swell) * fast + self.swell * slow) ** self.sharpness

    def swap(self, spot: Spot, t: float) -> float:
        """0 while columns 1/3 hold the light, 1 while 2/4 do, smooth in between."""
        u = (t / self.swap_period_s + spot.fixture * self.swap_spread) % 1.0
        tri = 1.0 - abs(2.0 * u - 1.0)  # 0 → 1 → 0 over the cycle
        a = self.swap_dwell / 2.0
        x = min(1.0, max(0.0, (tri - a) / (1.0 - 2.0 * a)))  # parked at 0 or 1 during the dwells
        return x * x * (3.0 - 2.0 * x)

    def gate(self, spot: Spot, t: float) -> float:
        """This column's share of the light: full, void, or somewhere in the exchange."""
        lit = self.swap(spot, t) if spot.void else 1.0 - self.swap(spot, t)
        return self.void_level + (1.0 - self.void_level) * lit

    def color(self, spot: Spot, t: float) -> RGB:
        w = self.wave(spot, t)
        return mix(self.trough, self.mid, w * 2.0) if w < 0.5 else mix(self.mid, self.crest, (w - 0.5) * 2.0)

    def intensity(self, spot: Spot, t: float) -> float:
        level = self.trough_level + (1.0 - self.trough_level) * self.wave(spot, t)
        return self.brightness * level * self.gate(spot, t)


AMBIENT_THEMES: dict[str, Theme] = {t.name: t for t in (WaveTheme("ember-waves"),)}

DRIFT_THEMES: dict[str, Theme] = {
    t.name: t
    for t in (
        DriftTheme(
            "moonlit",
            ((0.05, 0.15, 0.60), (0.00, 0.40, 0.50), (0.35, 0.45, 0.80), (0.15, 0.05, 0.50)),
        ),
        DriftTheme(
            "deep-forest",
            ((0.05, 0.50, 0.10), (0.00, 0.35, 0.30), (0.55, 0.35, 0.05), (0.20, 0.40, 0.05)),
            period_s=300.0,
        ),
        DriftTheme(
            "ember",
            ((0.80, 0.30, 0.00), (0.60, 0.05, 0.30), (0.50, 0.02, 0.02), (0.70, 0.50, 0.10)),
            period_s=280.0,
            brightness=0.75,
        ),
        DriftTheme(
            "violet-hour",
            ((0.40, 0.10, 0.70), (0.70, 0.20, 0.40), (0.15, 0.05, 0.50), (0.10, 0.20, 0.60)),
        ),
    )
}

SHOW_THEMES: dict[str, Theme] = {
    t.name: t
    for t in (
        DriftTheme(
            "aurora",
            ((0.00, 0.80, 0.40), (0.30, 0.10, 0.80), (0.00, 0.60, 0.80), (0.60, 0.00, 0.60)),
            period_s=45.0,
            spread=0.3,
            brightness=1.0,
            breathe_period_s=9.0,
            breathe_depth=0.35,
        ),
        DriftTheme(
            "starfall",
            ((0.70, 0.75, 1.00), (0.10, 0.20, 0.70), (0.90, 0.85, 0.60), (0.20, 0.10, 0.40)),
            period_s=60.0,
            spread=0.4,
            brightness=1.0,
            breathe_period_s=6.0,
            breathe_depth=0.5,
        ),
        DriftTheme(
            "pulse",
            ((0.90, 0.35, 0.05), (0.80, 0.05, 0.30), (0.95, 0.65, 0.15), (0.50, 0.00, 0.40)),
            period_s=50.0,
            spread=0.25,
            brightness=1.0,
            breathe_period_s=4.0,
            breathe_depth=0.45,
        ),
    )
}


def get_theme(name: str) -> Theme:
    theme = AMBIENT_THEMES.get(name) or SHOW_THEMES.get(name) or DRIFT_THEMES.get(name)
    if theme is None:
        raise KeyError(f"unknown lighting theme {name!r}")
    return theme


def pick_ambient(rng: random.Random, avoid: Theme | None = None) -> Theme:
    return _pick(rng, AMBIENT_THEMES, avoid)


def pick_show(rng: random.Random, avoid: Theme | None = None) -> Theme:
    return _pick(rng, SHOW_THEMES, avoid)


def _pick(rng: random.Random, pool: dict[str, Theme], avoid: Theme | None) -> Theme:
    candidates = [t for t in pool.values() if t is not avoid] or list(pool.values())
    return rng.choice(candidates)
