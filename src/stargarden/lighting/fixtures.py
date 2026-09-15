"""Fixture profiles (channel layouts), the patch (fixture → DMX address), and
rendering of per-fixture state into a DMX universe."""

from dataclasses import dataclass

from ..config import ConfigError, LightingConfig
from .color import BLACK, RGB, clamp01, rgb_to_rgbw

UNIVERSE_SIZE = 512

DIMMER, RED, GREEN, BLUE, WHITE, STROBE = "dimmer", "red", "green", "blue", "white", "strobe"

BUILTIN_PROFILES: dict[str, tuple[str, ...]] = {
    "rgb": (RED, GREEN, BLUE),
    "rgbw": (RED, GREEN, BLUE, WHITE),
    "dim_rgb": (DIMMER, RED, GREEN, BLUE),
    "dim_rgbw": (DIMMER, RED, GREEN, BLUE, WHITE),
    "rgb_strobe": (RED, GREEN, BLUE, STROBE),
    "dim_rgbw_strobe": (DIMMER, RED, GREEN, BLUE, WHITE, STROBE),
}


@dataclass(frozen=True)
class FixtureProfile:
    name: str
    channels: tuple[str, ...]

    @property
    def footprint(self) -> int:
        return len(self.channels)

    def has(self, channel: str) -> bool:
        return channel in self.channels


@dataclass(frozen=True)
class Fixture:
    name: str
    profile: FixtureProfile
    address: int  # 1-based DMX start address
    position: tuple[float, float] = (0.0, 0.0)

    @property
    def has_strobe(self) -> bool:
        return self.profile.has(STROBE)


@dataclass
class FixtureState:
    rgb: RGB = BLACK
    intensity: float = 1.0
    strobe: float = 0.0  # 0 = off, otherwise strobe rate 0..1


class Patch:
    def __init__(self, fixtures: tuple[Fixture, ...]) -> None:
        used: dict[int, str] = {}
        for f in fixtures:
            last = f.address + f.profile.footprint - 1
            if f.address < 1 or last > UNIVERSE_SIZE:
                raise ConfigError(f"fixture {f.name!r}: address {f.address} out of range for {f.profile.name}")
            for ch in range(f.address, last + 1):
                if ch in used:
                    raise ConfigError(f"fixture {f.name!r} overlaps {used[ch]!r} at channel {ch}")
                used[ch] = f.name
        self.fixtures = fixtures

    @classmethod
    def from_config(cls, cfg: LightingConfig) -> Patch:
        profiles = {name: FixtureProfile(name, chans) for name, chans in BUILTIN_PROFILES.items()}
        profiles.update({name: FixtureProfile(name, chans) for name, chans in cfg.profiles.items()})
        fixtures = []
        for fc in cfg.fixtures:
            if fc.profile not in profiles:
                raise ConfigError(f"fixture {fc.name!r}: unknown profile {fc.profile!r}")
            fixtures.append(Fixture(fc.name, profiles[fc.profile], fc.address, fc.position))
        return cls(tuple(fixtures))

    def __len__(self) -> int:
        return len(self.fixtures)

    @property
    def has_strobe(self) -> bool:
        return any(f.has_strobe for f in self.fixtures)

    def render(self, states: list[FixtureState]) -> bytes:
        universe = bytearray(UNIVERSE_SIZE)
        for fixture, state in zip(self.fixtures, states, strict=True):
            values = self._channel_values(fixture, state)
            for offset, name in enumerate(fixture.profile.channels):
                universe[fixture.address - 1 + offset] = _byte(values.get(name, 0.0))
        return bytes(universe)

    @staticmethod
    def _channel_values(fixture: Fixture, state: FixtureState) -> dict[str, float]:
        profile = fixture.profile
        intensity = clamp01(state.intensity)
        rgb = state.rgb
        values: dict[str, float] = {}
        if profile.has(DIMMER):
            values[DIMMER] = intensity
        else:
            rgb = (rgb[0] * intensity, rgb[1] * intensity, rgb[2] * intensity)
        if profile.has(WHITE):
            values[RED], values[GREEN], values[BLUE], values[WHITE] = rgb_to_rgbw(rgb)
        else:
            values[RED], values[GREEN], values[BLUE] = rgb
        if profile.has(STROBE):
            values[STROBE] = state.strobe
        return values


def _byte(x: float) -> int:
    return int(round(clamp01(x) * 255))
