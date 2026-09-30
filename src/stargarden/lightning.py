"""Lightning: a layer of its own, decoupled from the lighting themes.

A strike happens at a place. Its origin is one of the fixtures (a tree); the
flash is brightest there and ripples outward, later and dimmer, through the
other fixtures; thunder follows after a delay, panned to the same spot. Every
strike is composed fresh from the RNG so no two feel alike.
"""

import asyncio
import logging
import math
import random
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace

from .audio import AudioEngine
from .config import LightningConfig
from .lighting import LightingEngine, Patch
from .lighting.color import mix
from .lighting.fixtures import FixtureFrame
from .manifest import DiscreteEntry, Manifest

log = logging.getLogger(__name__)

LIGHTNING_COLOR = (0.85, 0.9, 1.0)  # for fixtures with no white cells to flash
MAIN_FLASH_S = (0.12, 0.22)  # the first flash, the punch
RESTRIKE_S = (0.03, 0.07)  # each return stroke
RESTRIKES = (1, 2, 2, 3, 3)  # how many return strokes follow, drawn uniformly: usually two or three


@dataclass(frozen=True)
class Flash:
    start: float
    end: float
    level: float
    level_end: float | None = None  # decays linearly to this when set
    strobe: bool = False

    def level_at(self, t: float) -> float:
        if not self.start <= t < self.end:
            return 0.0
        if self.level_end is None:
            return self.level
        return self.level + (self.level_end - self.level) * (t - self.start) / (self.end - self.start)


@dataclass(frozen=True)
class Strike:
    origin: str  # fixture name
    position: tuple[float, float]
    flashes: dict[str, tuple[Flash, ...]]  # per fixture, times relative to the strike
    duration: float
    thunder_delay: float


def compose_strike(
    rng: random.Random, positions: dict[str, tuple[float, float]], origin: str, thunder_delay: tuple[float, float]
) -> Strike:
    ox, oy = positions[origin]
    flashes: dict[str, list[Flash]] = defaultdict(list)

    def add(name: str, start: float, duration: float, level: float, strobe: bool = False, level_end: float | None = None) -> None:
        flashes[name].append(Flash(start, start + duration, min(1.0, level), level_end, strobe))

    def flash(t: float, dur: float, level: float, strobe: bool) -> None:
        add(origin, t, dur, level, strobe=strobe)
        for name, (x, y) in positions.items():  # the ripple: later and dimmer with distance
            if name == origin:
                continue
            distance = math.hypot(x - ox, y - oy)
            ripple = level * max(0.0, 0.8 - 0.3 * distance) * rng.uniform(0.85, 1.15)  # neighbors ~0.3, the far corner ~0.1
            if ripple > 0.03:
                add(name, t + distance * rng.uniform(0.02, 0.06), dur * rng.uniform(0.6, 1.0), ripple)

    t = 0.0
    if rng.random() < 0.3:  # a faint leader flicker before the main strike
        dur = rng.uniform(0.02, 0.04)
        add(origin, t, dur, rng.uniform(0.15, 0.3))
        t += dur + rng.uniform(0.05, 0.15)
    dur = rng.uniform(MAIN_FLASH_S[0], MAIN_FLASH_S[1])  # the punch: one long solid flash at full
    flash(t, dur, 1.0, strobe=False)
    t += dur + rng.uniform(0.03, 0.08)
    for _ in range(rng.choice(RESTRIKES)):  # return strokes: short, fast, nearly as bright, sometimes crackling
        dur = rng.uniform(RESTRIKE_S[0], RESTRIKE_S[1])
        flash(t, dur, rng.uniform(0.8, 1.0), strobe=rng.random() < 0.4)
        t += dur + rng.uniform(0.03, 0.10)
    add(origin, t, 0.3, 0.15, level_end=0.0)  # afterglow
    end = max(f.end for fs in flashes.values() for f in fs)
    return Strike(origin, (ox, oy), {k: tuple(v) for k, v in flashes.items()}, end, rng.uniform(*thunder_delay))


class StrikeOverlay:
    """Applies a strike to the lighting engine's frames while it lasts."""

    def __init__(self, strike: Strike, t0: float) -> None:
        self.strike = strike
        self.t0 = t0

    def finished(self, t: float) -> bool:
        return t - self.t0 >= self.strike.duration

    def apply(self, frames: list[FixtureFrame], patch: Patch, t: float) -> None:
        rel = t - self.t0
        for fixture, frame in zip(patch.fixtures, frames, strict=True):
            flashes = self.strike.flashes.get(fixture.name)
            if not flashes:
                continue
            level = max(f.level_at(rel) for f in flashes)
            if level <= 0.0:
                continue
            strobe = any(f.strobe and f.start <= rel < f.end for f in flashes)
            cells = fixture.mode.white_cells or fixture.mode.color_cells
            for cell in cells:
                state = frame[cell.name]
                if not fixture.mode.white_cells:  # no whites: push the color toward white instead
                    state.color = mix(state.color, LIGHTNING_COLOR, level)
                state.intensity = max(state.intensity, level)
                if strobe:
                    state.strobe = 1.0


class Lightning:
    def __init__(
        self,
        cfg: LightningConfig,
        patch: Patch,
        lighting: LightingEngine,
        audio: AudioEngine,
        manifest: Manifest,
        rng: random.Random | None = None,
        allowed: Callable[[], bool] = lambda: True,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.positions = {f.name: f.position for f in patch.fixtures}
        self._lighting = lighting
        self._audio = audio
        self._manifest = manifest
        self._rng = rng or random.Random()
        self._allowed = allowed
        self._clock = clock
        self.last_origin: str | None = None
        self.last_thunder: DiscreteEntry | None = None
        self.next_at = clock() + self._wait()

    def _wait(self) -> float:
        return max(self.cfg.min_interval_s, self._rng.expovariate(1.0 / max(self.cfg.mean_interval_s, 1.0)))

    def time_to_next(self) -> float | None:
        return max(0.0, self.next_at - self._clock()) if self.cfg.enabled else None

    @property
    def intervals_s(self) -> tuple[float, float]:
        return self.cfg.mean_interval_s, self.cfg.min_interval_s

    def set_intervals(self, mean_s: float, min_s: float) -> None:
        """Strikes about `mean_s` apart, never closer than `min_s`; the next one is drawn afresh."""
        if mean_s <= 0 or min_s <= 0:
            raise ValueError(f"lightning intervals must be positive, got mean {mean_s}, min {min_s}")
        self.cfg = replace(self.cfg, mean_interval_s=mean_s, min_interval_s=min_s)
        self.next_at = self._clock() + self._wait()

    async def run(self) -> None:
        while True:
            remaining = self.next_at - self._clock()
            if remaining > 0:
                await asyncio.sleep(min(remaining, 1.0))  # in short naps, so a rescheduled next_at is honoured
                continue
            if self.cfg.enabled and self._allowed():
                self.strike()
            self.next_at = self._clock() + self._wait()

    def strike(self, origin: str | None = None) -> Strike | None:
        if not self.positions:
            log.warning("lightning: no fixtures to strike")
            return None
        if origin is None:
            candidates = [n for n in self.positions if n != self.last_origin] or list(self.positions)
            origin = self._rng.choice(candidates)
        strike = compose_strike(self._rng, self.positions, origin, self.cfg.thunder_delay_s)
        self.last_origin = origin
        self._lighting.add_overlay(StrikeOverlay(strike, self._clock()))
        log.info("lightning: strike at %s, thunder in %.1fs", origin, strike.thunder_delay)
        try:
            asyncio.get_running_loop().call_later(strike.thunder_delay, self._thunder, strike)
        except RuntimeError:
            pass  # no event loop (tests): the caller can play thunder itself
        return strike

    def _thunder(self, strike: Strike) -> None:
        entry = self._manifest.pick_thunder(self._rng, avoid=self.last_thunder)
        if entry is None:
            log.warning("lightning: no thunder sounds in manifest")
            return
        self.last_thunder = entry
        lo, hi = self.cfg.thunder_delay_s
        closeness = 1.0 - (strike.thunder_delay - lo) / (hi - lo) if hi > lo else 1.0
        self._audio.play_thunder(entry, strike.position, gain=0.5 + 0.5 * closeness)
