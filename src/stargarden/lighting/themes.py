"""Lighting themes: how the trees look over time.

A theme answers "what color and intensity is fixture i at time t". DriftTheme
walks each fixture around a palette with a per-fixture phase offset, so the
trees share a mood without moving in unison.
"""

import math
import random
from dataclasses import dataclass

from .color import RGB, sample_palette


class Theme:
    """`index` is the fixture's position in the patch; zoned fixtures ask for
    fractional indices (fixture 2, zone 5 of 16 → 2.3125) so a bar shows a
    gradient of what its neighbors would show."""

    name: str
    lightning_ok: bool

    def color(self, index: float, count: int, t: float) -> RGB:
        raise NotImplementedError

    def intensity(self, index: float, count: int, t: float) -> float:
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
    lightning_ok: bool = False

    def color(self, index: float, count: int, t: float) -> RGB:
        return sample_palette(self.palette, t / self.period_s + index * self.spread)

    def intensity(self, index: float, count: int, t: float) -> float:
        phase = t / self.breathe_period_s + index * 0.37
        breathe = 0.5 + 0.5 * math.sin(2 * math.pi * phase)
        return self.brightness * (1.0 - self.breathe_depth * breathe)


AMBIENT_THEMES: dict[str, Theme] = {
    t.name: t
    for t in (
        DriftTheme(
            "moonlit",
            ((0.05, 0.15, 0.60), (0.00, 0.40, 0.50), (0.35, 0.45, 0.80), (0.15, 0.05, 0.50)),
            lightning_ok=True,
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
            lightning_ok=True,
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
    theme = AMBIENT_THEMES.get(name) or SHOW_THEMES.get(name)
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
