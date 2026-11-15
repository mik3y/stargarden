"""Dance patterns: lighting programs for after the sunset.

Each one paints the bars in blocks, moving on the beat the engine counts at
its tempo. There is no audio, so the tempo is a console setting. The moves are
eased, never cut or strobed.
"""

import math
from dataclasses import dataclass

from .lighting.color import RGB, mix
from .lighting.engine import Program, Spot

PINK: RGB = (1.0, 0.0, 0.45)
VIOLET: RGB = (0.45, 0.0, 1.0)
AMBER: RGB = (1.0, 0.35, 0.0)
CYAN: RGB = (0.0, 0.7, 1.0)
BLUE: RGB = (0.05, 0.1, 1.0)
PALETTE: tuple[RGB, ...] = (PINK, VIOLET, AMBER, CYAN, BLUE)
FRONTS: tuple[RGB, ...] = (PINK, AMBER, CYAN, VIOLET)  # the color pairs of chase and checker, phrase by phrase
BACKS: tuple[RGB, ...] = (BLUE, VIOLET, PINK, AMBER)
PHRASE_BEATS = 16.0
PHRASE_FADE_BEATS = 2.0


def _noise(*keys: int) -> float:
    """A fixed pseudo-random number in 0..1 for a tuple of integers."""
    h = 0x9E3779B9
    for k in keys:
        h = ((h ^ (k & 0xFFFFFFFF)) * 0x85EBCA6B) & 0xFFFFFFFF
        h ^= h >> 13
    return ((h * 0xC2B2AE35) & 0xFFFFFFFF) / 2**32


def _ease(u: float) -> float:
    """Smoothstep, clamped."""
    u = min(1.0, max(0.0, u))
    return u * u * (3.0 - 2.0 * u)


def _pick(step: int, *keys: int) -> RGB:
    """A palette color for a step, never the one the step before had."""
    index = 0
    for k in range(step % 64 + 1):  # walk forward from a common start, hopping 1..n-1 places each step
        index = (index + 1 + int(_noise(k, *keys) * (len(PALETTE) - 1))) % len(PALETTE)
    return PALETTE[index]


def _phrase(colors: tuple[RGB, ...], beat: float, offset: int = 0) -> RGB:
    """The color for the current sixteen-beat phrase, easing in from the last phrase's over its first two beats."""
    k = math.floor(beat / PHRASE_BEATS)
    u = _ease((beat - k * PHRASE_BEATS) / PHRASE_FADE_BEATS)
    return mix(colors[(k - 1 + offset) % len(colors)], colors[(k + offset) % len(colors)], u)


@dataclass(frozen=True)
class Blocks:
    """Each half of a bar is a block holding one color for eight beats. The blocks
    take turns changing, a pair on different bars every two beats, and a few sit
    nearly dark."""

    name: str = "blocks"
    hold_beats: float = 8.0
    stagger_beats: float = 2.0
    fade_beats: float = 1.0
    dark_share: float = 0.25
    dark_level: float = 0.06

    def _block(self, block: int, beat: float) -> tuple[RGB, float, float]:
        """A block's color and level in its current hold, and how far into the hold it is in beats."""
        local = beat + block * self.stagger_beats
        step = math.floor(local / self.hold_beats)
        level = self.dark_level if _noise(block, step, 7) < self.dark_share else 1.0
        return _pick(step, block), level, local - step * self.hold_beats

    def cell(self, spot: Spot, beat: float) -> tuple[RGB, float]:
        block = spot.bar * 2 + spot.col * 2 // spot.cols
        color, level, into = self._block(block, beat)
        if into >= self.fade_beats:
            return color, level
        was_color, was_level, _ = self._block(block, beat - self.fade_beats)
        u = _ease(into / self.fade_beats)
        return mix(was_color, color, u), was_level + (level - was_level) * u

    def accent(self, beat: float) -> RGB:
        return _phrase(PALETTE, beat)


@dataclass(frozen=True)
class Chase:
    """Two blocks of light run along the bars, half the room apart, each trailing a
    fading tail over a dim violet floor. Their colors change every sixteen beats."""

    name: str = "chase"
    beats_per_column: float = 1.0
    tail: float = 4.0  # columns
    floor: RGB = VIOLET
    floor_level: float = 0.05

    def cell(self, spot: Spot, beat: float) -> tuple[RGB, float]:
        columns = spot.columns
        head = beat / self.beats_per_column
        best, color = 0.0, self.floor
        for k, runner in enumerate((_phrase(FRONTS, beat), _phrase(BACKS, beat))):
            behind = (head + k * columns / 2 - spot.column) % columns
            glow = _ease(behind) if behind < 1.0 else max(0.0, 1.0 - (behind - 1.0) / self.tail) ** 2
            if glow > best:
                best, color = glow, runner
        if best <= self.floor_level:
            return self.floor, self.floor_level
        return color, best

    def accent(self, beat: float) -> RGB:
        return _phrase(FRONTS, beat)


@dataclass(frozen=True)
class Checker:
    """A checkerboard of two colors over the cells that trades places every two beats.
    The pair of colors changes every sixteen."""

    name: str = "checker"
    swap_beats: float = 2.0
    fade_beats: float = 0.5
    back_level: float = 0.45  # the second color sits behind the first

    def cell(self, spot: Spot, beat: float) -> tuple[RGB, float]:
        front, back = _phrase(FRONTS, beat), _phrase(BACKS, beat)
        step = math.floor(beat / self.swap_beats)
        u = _ease((beat - step * self.swap_beats) / self.fade_beats)
        on = (spot.column + spot.row + step) % 2 == 0
        share = u if on else 1.0 - u  # how much of the front color this cell shows
        return mix(back, front, share), self.back_level + (1.0 - self.back_level) * share

    def accent(self, beat: float) -> RGB:
        return _phrase(FRONTS, beat)


@dataclass(frozen=True)
class Pulse:
    """The bars take a beat each in turn. A bar swells from its middle columns out
    on its beat and sinks back until its turn comes round. Each bar's color moves
    on every sixteen beats."""

    name: str = "pulse"
    floor_level: float = 0.12
    attack_beats: float = 0.25
    decay: float = 1.1  # per beat
    edge_lag_beats: float = 0.35  # the outer columns follow the middle

    def cell(self, spot: Spot, beat: float) -> tuple[RGB, float]:
        edge = abs((spot.col + 0.5) / spot.cols - 0.5) * 2.0  # 0 at the middle of the bar, toward 1 at its ends
        since = (beat - spot.bar - edge * self.edge_lag_beats) % spot.bars
        swell = _ease(since / self.attack_beats) * math.exp(-self.decay * max(0.0, since - self.attack_beats))
        return _phrase(PALETTE, beat, spot.bar), self.floor_level + (1.0 - self.floor_level) * swell

    def accent(self, beat: float) -> RGB:
        return _phrase(PALETTE, beat)


PATTERNS: dict[str, Program] = {p.name: p for p in (Blocks(), Chase(), Checker(), Pulse())}
