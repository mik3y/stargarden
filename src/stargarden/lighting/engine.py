"""Lighting render loop: theme (with crossfades) × master fade × overlays → DMX."""

import asyncio
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..config import LightingConfig
from .color import RGB, mix
from .drivers import DmxDriver
from .fixtures import FixtureState, Patch
from .themes import Theme

log = logging.getLogger(__name__)

LIGHTNING_COLOR = (0.85, 0.9, 1.0)


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
        self._prev_theme: Theme | None = None
        self._theme_fade: _Ramp | None = None
        self._master = _Ramp(0.0, 0.0, 0.0, 0.0)
        self._flashes: list[tuple[float, float]] = []  # (start_t, end_t)
        self._next_lightning = self._schedule_lightning(clock())
        self.last_states: list[FixtureState] = [FixtureState() for _ in patch.fixtures]

    # -- control --------------------------------------------------------------

    def set_theme(self, theme: Theme, fade_s: float = 0.0) -> None:
        if theme is self.theme:
            return
        log.info("lighting: theme %s (fade %.0fs)", theme.name, fade_s)
        now = self._clock()
        self._prev_theme = self.theme
        self.theme = theme
        self._theme_fade = _Ramp(0.0, 1.0, now, fade_s)

    def fade_master(self, target: float, seconds: float) -> None:
        now = self._clock()
        self._master = _Ramp(self._master.at(now), target, now, seconds)

    def master(self) -> float:
        return self._master.at(self._clock())

    def trigger_lightning(self) -> None:
        now = self._clock()
        t = now + 0.05
        for _ in range(self._rng.randint(2, 4)):
            duration = self._rng.uniform(0.06, 0.18)
            self._flashes.append((t, t + duration))
            t += duration + self._rng.uniform(0.05, 0.35)
        log.info("lighting: lightning")

    # -- rendering ------------------------------------------------------------

    def frame(self, t: float) -> list[FixtureState]:
        master = self._master.at(t)
        blend = self._theme_fade.at(t) if self._theme_fade else 1.0
        if blend >= 1.0:
            self._prev_theme, self._theme_fade = None, None
        self._flashes = [f for f in self._flashes if f[1] > t]
        flashing = any(f[0] <= t < f[1] for f in self._flashes)
        count = len(self.patch.fixtures)
        states = []
        for i, fixture in enumerate(self.patch.fixtures):
            profile = fixture.profile
            if flashing and profile.can_flash and not profile.has_white_unit:
                states.append(FixtureState(rgb=LIGHTNING_COLOR, intensity=1.0, strobe=1.0))
                continue
            n = profile.rgb_zones
            zones = tuple(self._color(i + profile.zone_x(z), count, t, blend) for z in range(n)) if n > 1 else ()
            rgb = zones[n // 2] if zones else self._color(i, count, t, blend)
            state = FixtureState(rgb=rgb, intensity=self._intensity(i, count, t, blend) * master, zones=zones)
            if flashing and profile.has_white_unit:  # the whites flash; the color program carries on
                state.white, state.strobe = 1.0, 1.0
            states.append(state)
        self.last_states = states
        return states

    def _color(self, index: float, count: int, t: float, blend: float) -> RGB:
        rgb = self.theme.color(index, count, t)
        if self._prev_theme is not None and blend < 1.0:
            return mix(self._prev_theme.color(index, count, t), rgb, blend)
        return rgb

    def _intensity(self, index: float, count: int, t: float, blend: float) -> float:
        value = self.theme.intensity(index, count, t)
        if self._prev_theme is not None and blend < 1.0:
            prev = self._prev_theme.intensity(index, count, t)
            return prev + (value - prev) * blend
        return value

    def _schedule_lightning(self, now: float) -> float:
        cfg = self.cfg.lightning
        wait = max(cfg.min_interval_s, self._rng.expovariate(1.0 / max(cfg.mean_interval_s, 1.0)))
        return now + wait

    def _maybe_lightning(self, now: float) -> None:
        if now < self._next_lightning:
            return
        self._next_lightning = self._schedule_lightning(now)
        if self.cfg.lightning.enabled and self.theme.lightning_ok and self.patch.can_flash and self.master() > 0.5:
            self.trigger_lightning()

    async def run(self) -> None:
        period = 1.0 / self.cfg.fps
        self.driver.open()
        log.info("lighting: %d fixture(s) via %s at %.0f fps", len(self.patch), self.driver.name, self.cfg.fps)
        try:
            next_frame = self._clock()
            while True:
                now = self._clock()
                self._maybe_lightning(now)
                self.driver.send(self.patch.render(self.frame(now)))
                next_frame += period
                await asyncio.sleep(max(0.0, next_frame - self._clock()))
        finally:
            self.driver.send(self.patch.render([FixtureState() for _ in self.patch.fixtures]))
            self.driver.close()
