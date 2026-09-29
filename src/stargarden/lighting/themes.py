"""Lighting themes: how the fixtures look over time.

A theme answers "what color and intensity is this spot at time t", where a
spot is a fixture in the patch and, for zoned fixtures, a cell of its grid.
DriftTheme walks each fixture around a palette with a per-fixture phase offset,
so the trees share a mood without moving in unison. WaveTheme, the ambient
program, sends waves of amber and orange along the bars with every other
column dark. TideTheme, the other ambient program, washes a broad green swell
around the ring of columns and back. ChaseTheme, the show program, runs a
column of light around the room one way, then the other, then breaks into an
odd/even dance.
"""

import math
import random
from dataclasses import dataclass

from .color import BLACK, RGB, mix, sample_palette


@dataclass(frozen=True)
class Spot:
    """Where a theme is sampled: fixture `fixture` of `count`, and for a zoned
    fixture the cell at (col of cols, row of rows) in its grid. `index` is the
    continuous position along the patch (fixture 2, column 5 of 16 → 2.34), so
    a bar shows a gradient of what its neighbors would show. `ring` is the
    column's place going clockwise around the space (fixtures ordered by the
    bearing of their position, columns left to right within each), of
    `ring_count` columns in all."""

    fixture: int
    count: int
    col: int = 0
    cols: int = 1
    row: int = 0
    rows: int = 1
    ring: int = 0
    ring_count: int = 1

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


@dataclass(frozen=True)
class TideTheme(Theme):
    """A swell of green washing around the ring and back.

    One broad crest, about a bar wide, travels clockwise around the ring of
    columns (each bar counting as its four columns), eases to a stop, washes
    back the other way, and repeats. The crest's place on the ring follows a
    cosine of time, fastest mid-lap and still at each turn, so nothing ever
    jolts. Away from the crest the columns hold a dim deep green, with a faint
    slower ripple running the other way round so the trough is never flat.
    Colors stay on the green line, from moss to spring green, never toward white.
    """

    name: str
    trough: RGB = (0.0, 0.12, 0.03)  # moss
    mid: RGB = (0.05, 0.55, 0.10)  # leaf
    crest: RGB = (0.40, 1.0, 0.20)  # spring green
    laps: float = 1.0  # around the ring before turning back
    period_s: float = 64.0  # there and back
    width: float = 4.0  # columns from the crest's centre to its edge, a bar's worth each side
    ripple_share: float = 0.18  # the counter-running ripple's share of the blend
    ripple_cycles: int = 2  # ripple crests around the ring; a whole number, so it meets itself at the seam
    ripple_period_s: float = 21.0
    trough_level: float = 0.3  # intensity in a trough, relative to a crest
    brightness: float = 1.0

    def head(self, spot: Spot, t: float) -> float:
        """The crest's position on the ring, in columns from where it starts; clockwise out, back again."""
        u = (t / self.period_s) % 1.0
        return self.laps * spot.ring_count * (0.5 - 0.5 * math.cos(2 * math.pi * u))

    def wave(self, spot: Spot, t: float) -> float:
        """0 in a trough, 1 at the crest."""
        n = spot.ring_count
        d = (spot.ring - self.head(spot, t) + n / 2) % n - n / 2  # signed distance to the crest, the short way round
        crest = 0.5 + 0.5 * math.cos(math.pi * d / self.width) if abs(d) < self.width else 0.0
        ripple = 0.5 + 0.5 * math.sin(2 * math.pi * (self.ripple_cycles * spot.ring / n + t / self.ripple_period_s))
        return (1.0 - self.ripple_share) * crest + self.ripple_share * ripple

    def color(self, spot: Spot, t: float) -> RGB:
        w = self.wave(spot, t)
        return mix(self.trough, self.mid, w * 2.0) if w < 0.5 else mix(self.mid, self.crest, (w - 0.5) * 2.0)

    def intensity(self, spot: Spot, t: float) -> float:
        return self.brightness * (self.trough_level + (1.0 - self.trough_level) * self.wave(spot, t))


def _smoothstep(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


@dataclass(frozen=True)
class ChaseTheme(Theme):
    """A column of light circling the space, in blue and purple.

    Three movements, repeating: the head runs clockwise around the ring of
    columns for a few laps with a short tail fading behind it, then runs the
    other way, then the room breaks into a dance where the odd and even
    columns take turns on a steady beat. Between hits the room holds a faint
    indigo glow rather than going black. Movements cross-fade into each other.
    The head's color slides between blue and purple as it goes round.
    """

    name: str
    blue: RGB = (0.05, 0.22, 1.0)
    purple: RGB = (0.55, 0.04, 1.0)
    glow: RGB = (0.03, 0.03, 0.4)  # the room between hits
    glow_level: float = 0.06
    step_s: float = 0.4  # one column to the next
    laps: int = 2  # per direction
    tail: float = 1.6  # columns of afterglow behind the head
    dance_s: float = 12.0
    dance_step_s: float = 0.5  # odd/even swap on this beat
    dance_floor: float = 0.12  # the resting side of the dance, relative to the lit side
    fade_s: float = 1.2  # cross-fade between movements
    hue_period_s: float = 9.0  # blue → purple → blue

    # -- timeline -------------------------------------------------------------

    def _chase_s(self, spot: Spot) -> float:
        return self.laps * spot.ring_count * self.step_s

    def _cycle_s(self, spot: Spot) -> float:
        return 2 * self._chase_s(spot) + self.dance_s

    def _weights(self, spot: Spot, t: float) -> tuple[float, float, float]:
        """How much of each movement (clockwise, counter, dance) applies at t; they sum to 1."""
        cycle = self._cycle_s(spot)
        u = t % cycle
        bounds = (0.0, self._chase_s(spot), 2 * self._chase_s(spot))

        def past(b: float) -> float:  # 0 before boundary b, 1 after, smooth across fade_s (wrapping)
            d = (u - b + cycle / 2) % cycle - cycle / 2
            return _smoothstep(0.5 + d / self.fade_s)

        s0, s1, s2 = (past(b) for b in bounds)
        return s0 * (1 - s1), s1 * (1 - s2), s2 * (1 - s0)

    # -- movements ------------------------------------------------------------

    def _head_color(self, spot: Spot, t: float) -> RGB:
        u = 0.5 + 0.5 * math.sin(2 * math.pi * (t / self.hue_period_s + spot.ring / max(1, spot.ring_count)))
        return mix(self.blue, self.purple, u)

    def _chase(self, spot: Spot, tau: float, clockwise: bool) -> float:
        n = spot.ring_count
        steps = tau / self.step_s
        head = (steps if clockwise else -steps) % n
        behind = (head - spot.ring) % n if clockwise else (spot.ring - head) % n  # columns since the head passed
        return max(0.0, 1.0 - behind / self.tail) ** 1.5

    def _dance(self, spot: Spot, tau: float) -> tuple[RGB, float]:
        beats = tau / self.dance_step_s
        lit = int(beats) % 2 == spot.ring % 2
        frac = beats % 1.0
        color = self.blue if spot.ring % 2 == 0 else self.purple
        return color, (1.0 - 0.5 * frac) if lit else self.dance_floor

    # -- theme ----------------------------------------------------------------

    def sample(self, spot: Spot, t: float) -> tuple[RGB, float]:
        w_cw, w_ccw, w_dance = self._weights(spot, t)
        u = t % self._cycle_s(spot)
        chase = self._chase_s(spot)
        parts: list[tuple[RGB, float, float]] = []  # color, level, weight
        if w_cw > 0:
            parts.append((self._head_color(spot, t), self._chase(spot, u, True), w_cw))
        if w_ccw > 0:
            parts.append((self._head_color(spot, t), self._chase(spot, u - chase, False), w_ccw))
        if w_dance > 0:
            color, level = self._dance(spot, u - 2 * chase)
            parts.append((color, level, w_dance))
        level = sum(lv * w for _, lv, w in parts)
        total = self.glow_level + level
        color: RGB = BLACK
        for c, lv, w in parts:
            color = tuple(a + b * lv * w / total for a, b in zip(color, c, strict=True))
        color = tuple(a + g * self.glow_level / total for a, g in zip(color, self.glow, strict=True))
        return color, min(1.0, total)

    def color(self, spot: Spot, t: float) -> RGB:
        return self.sample(spot, t)[0]

    def intensity(self, spot: Spot, t: float) -> float:
        return self.sample(spot, t)[1]


AMBIENT_THEMES: dict[str, Theme] = {t.name: t for t in (WaveTheme("ember-waves"), TideTheme("green-tide"))}
SHOW_THEMES: dict[str, Theme] = {t.name: t for t in (ChaseTheme("orbit"),)}

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
