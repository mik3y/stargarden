"""Lighting themes: how the fixtures look over time.

A theme answers "what color and intensity is this spot at time t", where a
spot is a fixture in the patch and, for zoned fixtures, a cell of its grid.
DriftTheme walks each fixture around a palette with a per-fixture phase offset,
so the trees share a mood without moving in unison. WaveTheme, the ambient
program, sends waves of amber and orange along the bars with every other
column dark. TideTheme, the other ambient program, washes a broad green swell
around the ring of columns and back. ChaseTheme, the show program, runs a
column of light around the room one way, then the other, then breaks into an
odd/even dance. StormTheme and SparkleTheme, the other show programs, leave most
of the ring dark: a few violet islands with white flashes on the beat, and stars
flaring out of a deep blue sky.
"""

import math
import random
from collections.abc import Collection
from dataclasses import dataclass
from functools import lru_cache

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
    tempo_bpm: float | None = None  # the tempo the theme is written at; the engine scales its clock to a track's tempo
    snaps: bool = False  # the look is meant to cut and flash; the slow programs must stay smooth

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
    Colors stay on the green line, from moss to spring green, nearly pure so the
    LEDs read green rather than lime.
    """

    name: str
    # DMX is linear light, so a little red or blue drives the LEDs far harder than the same
    # value looks on a screen swatch: keep the greens nearly pure or the crest washes to lime.
    trough: RGB = (0.0, 0.12, 0.02)  # moss
    mid: RGB = (0.02, 0.55, 0.03)  # leaf
    crest: RGB = (0.10, 1.0, 0.04)  # spring green
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

    Written at 120 BPM: the dance swaps every beat and the chase steps every
    0.8 beat. During a show the engine runs the theme's clock at the track's
    tempo over this one, so the whole program breathes with the music.
    """

    name: str
    tempo_bpm: float | None = 120.0
    snaps: bool = True
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


@lru_cache(maxsize=16384)
def _noise(*keys: int) -> float:
    """A number in [0, 1) that looks random but is fixed for its keys, so a theme can make
    random-looking choices (which column, whether at all) that hold still from frame to frame."""
    mask = (1 << 64) - 1
    h = 0x9E3779B97F4A7C15
    for k in keys:
        h = ((h ^ (k & mask)) * 0xBF58476D1CE4E5B9) & mask
        h ^= h >> 29
    return (h >> 11) / float(1 << 53)


@dataclass(frozen=True)
class StormTheme(Theme):
    """Violet islands in the dark, and white flashes on the beat.

    Most of the ring is dark. A few columns at a time hold a deep violet that
    swells up and fades on a slow clock of its own, each column on its own phase
    and period, so the lit set wanders around the space without ever moving in
    step. On roughly every other beat one column takes a white flash that falls
    back to violet within a quarter second; now and then the whole ring flashes
    at once. Written at 120 BPM: the flashes land on the track's beats.
    """

    name: str
    tempo_bpm: float | None = 120.0
    snaps: bool = True
    deep: RGB = (0.22, 0.0, 0.55)  # an island as it swells in
    violet: RGB = (0.55, 0.04, 1.0)  # at full
    white: RGB = (1.0, 0.95, 1.0)  # a flash; a breath of violet keeps it from reading cold
    glow_level: float = 0.02  # the dark between islands
    island_period_s: float = 14.0  # one swell in and out; each column varies this by up to ±20 %
    island_share: float = 0.3  # the share of the swell a column spends lit
    beat_s: float = 0.5
    flash_chance: float = 0.45  # per beat
    sheet_chance: float = 0.06  # a flash that takes the whole ring rather than one column
    flash_s: float = 0.25  # a flash is over in this long
    brightness: float = 0.85  # an island at full; the flashes go to 1.0 above it

    def island(self, spot: Spot, t: float) -> float:
        """How lit this column's island is, 0..1: parked at 0 most of the time."""
        period = self.island_period_s * (0.8 + 0.4 * _noise(spot.ring, 1))
        u = (t / period + _noise(spot.ring, 2)) % 1.0
        swell = 0.5 + 0.5 * math.cos(2 * math.pi * u)  # 1 at the top of the swell
        return _smoothstep((swell - (1.0 - self.island_share)) / self.island_share)

    def flash(self, spot: Spot, t: float) -> float:
        """How much of a flash this column shows, 0..1, from this beat's flash or the last one's tail."""
        level = 0.0
        beat = int(t // self.beat_s)
        for k in (beat - 1, beat):
            if _noise(k, 7) >= self.flash_chance:
                continue
            column = int(_noise(k, 8) * spot.ring_count)
            if column != spot.ring and _noise(k, 9) >= self.sheet_chance:
                continue
            dt = t - k * self.beat_s
            if 0.0 <= dt < self.flash_s:
                level = max(level, (1.0 - dt / self.flash_s) ** 2)
        return level

    def sample(self, spot: Spot, t: float) -> tuple[RGB, float]:
        lit = self.island(spot, t)
        base_color = mix(self.deep, self.violet, lit)
        base = max(self.glow_level, lit * self.brightness)
        f = self.flash(spot, t)
        return mix(base_color, self.white, f), base + (1.0 - base) * f

    def color(self, spot: Spot, t: float) -> RGB:
        return self.sample(spot, t)[0]

    def intensity(self, spot: Spot, t: float) -> float:
        return self.sample(spot, t)[1]


@dataclass(frozen=True)
class SparkleTheme(Theme):
    """A dark blue sky with stars coming out.

    The floor is a faint deep blue, barely there, with a slow swell drifting
    round the ring so the dark is never flat. On it, single cells flare ice-white
    and die away to blue over half a second: stars, a scatter of them on each
    beat and a stray one or two in between. Most cells are dark at any moment.
    Written at 120 BPM: the scatters land on the track's beats.
    """

    name: str
    tempo_bpm: float | None = 120.0
    snaps: bool = True
    floor: RGB = (0.0, 0.05, 0.3)
    floor_level: float = 0.05
    swell_depth: float = 0.8  # the floor rises by this share at the swell's crest
    swell_period_s: float = 23.0  # one trip round the ring
    star: RGB = (0.75, 0.88, 1.0)  # a star at its brightest
    blue: RGB = (0.1, 0.3, 1.0)  # what it fades through
    beat_s: float = 0.5
    on_beat_chance: float = 0.10  # per cell, on the half-slot that starts a beat
    off_beat_chance: float = 0.03  # per cell, on the half-slot between beats
    attack_s: float = 0.04
    decay_s: float = 0.5
    brightness: float = 1.0

    @property
    def slot_s(self) -> float:
        return self.beat_s / 2.0

    def stars(self, spot: Spot, t: float) -> float:
        """The light of every star still burning on this cell, 0..1."""
        slot = int(t // self.slot_s)
        tail = int((self.attack_s + self.decay_s) // self.slot_s) + 1
        level = 0.0
        for k in range(slot - tail, slot + 1):
            chance = self.on_beat_chance if k % 2 == 0 else self.off_beat_chance
            if _noise(spot.ring, spot.row, k, 1) >= chance:
                continue
            dt = t - (k + 0.8 * _noise(spot.ring, spot.row, k, 2)) * self.slot_s
            if dt < 0.0:
                continue
            if dt < self.attack_s:
                level += dt / self.attack_s
            elif dt < self.attack_s + self.decay_s:
                level += (1.0 - (dt - self.attack_s) / self.decay_s) ** 2
        return min(1.0, level)

    def sky(self, spot: Spot, t: float) -> float:
        swell = 0.5 + 0.5 * math.sin(2 * math.pi * (t / self.swell_period_s - spot.ring / max(1, spot.ring_count)))
        return self.floor_level * (1.0 + self.swell_depth * swell)

    def sample(self, spot: Spot, t: float) -> tuple[RGB, float]:
        star = self.stars(spot, t)
        sky = self.sky(spot, t)
        color = mix(self.floor, mix(self.blue, self.star, star), star)
        return color, min(1.0, sky + star * self.brightness)

    def color(self, spot: Spot, t: float) -> RGB:
        return self.sample(spot, t)[0]

    def intensity(self, spot: Spot, t: float) -> float:
        return self.sample(spot, t)[1]


AMBIENT_THEMES: dict[str, Theme] = {t.name: t for t in (WaveTheme("ember-waves"), TideTheme("green-tide"))}
SHOW_THEMES: dict[str, Theme] = {t.name: t for t in (ChaseTheme("orbit"), StormTheme("violet-storm"), SparkleTheme("starfield"))}

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


def pick_ambient(rng: random.Random, avoid: Theme | None = None, enabled: Collection[str] | None = None) -> Theme:
    return _pick(rng, AMBIENT_THEMES, avoid, enabled)


def pick_show(rng: random.Random, avoid: Theme | None = None, enabled: Collection[str] | None = None) -> Theme:
    return _pick(rng, SHOW_THEMES, avoid, enabled)


def _pick(rng: random.Random, pool: dict[str, Theme], avoid: Theme | None, enabled: Collection[str] | None) -> Theme:
    """A random theme from the pool, not `avoid` if there is a choice, and only from
    `enabled` names when given (the whole pool if that leaves nothing)."""
    pool_themes = [t for t in pool.values() if enabled is None or t.name in enabled] or list(pool.values())
    candidates = [t for t in pool_themes if t is not avoid] or pool_themes
    return rng.choice(candidates)
