"""Fixture profiles (channel layouts), the patch (fixture → DMX address), and
rendering of per-fixture state into a DMX universe.

A profile is a tuple of channel roles in DMX order. Roles the renderer knows
are listed below; anything else ("color_macro", "ct_preset", ...) is emitted as
0 so the fixture stays in plain color mode. Zoned fixtures (LED bars) use
indexed roles like "red:3" or "white:7"; a role may appear more than once when
a fixture duplicates a control block (e.g. outer and inner dimmers).
"""

import re
from dataclasses import dataclass

from ..config import ConfigError, LightingConfig
from .color import BLACK, RGB, clamp01, rgb_to_rgbw

UNIVERSE_SIZE = 512

RED, GREEN, BLUE, WHITE = "red", "green", "blue", "white"
DIMMER, DIMMER_FINE = "dimmer", "dimmer_fine"  # 8-bit, or 16-bit when both are present
# A dimmer that is the only control over a fixture's white LEDs: driven by the
# white component of the color rather than the master intensity.
INNER_DIMMER, INNER_DIMMER_FINE = "inner_dimmer", "inner_dimmer_fine"
STROBE = "strobe"  # single channel: 0 = open, else rate slow→fast
# Effect/rate/duration trio (ADJ style): the effect channel selects plain strobe
# while flashing and the rate/duration channels carry the intensity of it.
STROBE_EFFECT, STROBE_RATE, STROBE_DURATION = "strobe_effect", "strobe_rate", "strobe_duration"
STROBE_EFFECT_OPEN, STROBE_EFFECT_STROBE = 0, 4  # ADJ: 000-002 open, 003-005 strobe
WHITE_GROUP = "white_group"  # "white_group:N": one white channel per group of zones

_ZONED = re.compile(r"^(red|green|blue|white|white_group):(\d+)$")


def _zoned(role: str, count: int) -> tuple[str, ...]:
    return tuple(f"{role}:{i}" for i in range(1, count + 1))


def _rgb_zones(count: int) -> tuple[str, ...]:
    return tuple(f"{c}:{i}" for i in range(1, count + 1) for c in (RED, GREEN, BLUE))


def _jolt_bar_fx2_profiles() -> dict[str, FixtureProfile]:
    """ADJ Jolt Bar FX2, all 17 DMX modes (ADJ "DMX Traits" sheet / manual JOL286;
    cross-checked against the Lightkey profile in docs/fixtures/).

    The bar is three rows of 16: RGB zones along the top row then the bottom row
    (zone 17 sits under zone 1), cool-white zones in the middle row. Modes differ
    in how many zones are exposed and which control blocks come along: a strobe
    trio, program/color macros (left at 0), CT presets + green shift (left at 0),
    and in the bigger modes a duplicated "inner" dimmer/strobe block for the
    whites. In 18/20CH there is no white channel at all: the inner dimmer *is*
    the white. Select the mode on the fixture's menu; the profile name says which.
    """
    strobe = (STROBE_EFFECT, STROBE_RATE, STROBE_DURATION)
    dim = (DIMMER, DIMMER_FINE)
    inner_dim = (INNER_DIMMER, INNER_DIMMER_FINE)
    program = ("program_macro", "program_speed")
    color_macro = ("color_macro",)
    ct = ("ct_preset", "green_shift")
    groups = _zoned(WHITE_GROUP, 4)
    modes = {
        "jolt_bar_fx2_6ch": (RED, GREEN, BLUE, WHITE, *dim),
        "jolt_bar_fx2_9ch": (RED, GREEN, BLUE, WHITE, *dim, *strobe),
        "jolt_bar_fx2_13ch": (RED, GREEN, BLUE, WHITE, *color_macro, *dim, *strobe, "program_macro", "program_macro", "program_speed"),
        "jolt_bar_fx2_16ch": _rgb_zones(4) + _zoned(WHITE, 4),
        "jolt_bar_fx2_18ch": (RED, GREEN, BLUE, *color_macro, *dim, *strobe, *program, *inner_dim, *strobe, *program),
        "jolt_bar_fx2_20ch": (RED, GREEN, BLUE, *ct, *color_macro, *dim, *strobe, *program, *inner_dim, *strobe, *program),
        "jolt_bar_fx2_32ch": _rgb_zones(8) + _zoned(WHITE, 8),
        "jolt_bar_fx2_34ch": _rgb_zones(8) + ct + _zoned(WHITE, 8),
        "jolt_bar_fx2_38ch": _rgb_zones(8) + dim + strobe + groups + dim + strobe,
        "jolt_bar_fx2_43ch": _rgb_zones(8) + color_macro + dim + strobe + program + groups + dim + strobe + program,
        "jolt_bar_fx2_45ch": _rgb_zones(8) + ct + color_macro + dim + strobe + program + groups + dim + strobe + program,
        "jolt_bar_fx2_64ch": _rgb_zones(16) + _zoned(WHITE, 16),
        "jolt_bar_fx2_78ch": _rgb_zones(16) + _zoned(WHITE, 16) + dim + strobe + groups + dim + strobe,
        "jolt_bar_fx2_80ch": _rgb_zones(16) + ct + _zoned(WHITE, 16) + dim + strobe + groups + dim + strobe,
        "jolt_bar_fx2_112ch": _rgb_zones(32) + _zoned(WHITE, 16),
        "jolt_bar_fx2_127ch": _rgb_zones(32) + color_macro + dim + strobe + program + _zoned(WHITE, 16) + dim + strobe + program,
        "jolt_bar_fx2_129ch": _rgb_zones(32) + ct + color_macro + dim + strobe + program + _zoned(WHITE, 16) + dim + strobe + program,
    }
    return {name: FixtureProfile(name, channels, zone_rows=2) for name, channels in modes.items()}


@dataclass(frozen=True)
class FixtureProfile:
    name: str
    channels: tuple[str, ...]
    zone_rows: int = 1  # RGB zones are numbered row by row, left to right

    @property
    def footprint(self) -> int:
        return len(self.channels)

    def has(self, channel: str) -> bool:
        return channel in self.channels

    def _zone_count(self, role: str) -> int:
        return max((int(m.group(2)) for ch in self.channels if (m := _ZONED.match(ch)) and m.group(1) == role), default=0)

    @property
    def rgb_zones(self) -> int:
        return self._zone_count(RED)

    @property
    def zones_per_row(self) -> int:
        return max(1, -(-self.rgb_zones // max(1, self.zone_rows)))

    def zone_x(self, zone: int) -> float:
        """Horizontal position (0..1) of RGB zone `zone` (0-based) along the fixture."""
        per_row = self.zones_per_row
        return ((zone % per_row) + 0.5) / per_row

    @property
    def white_zones(self) -> int:
        return self._zone_count(WHITE)

    @property
    def white_groups(self) -> int:
        return self._zone_count(WHITE_GROUP)

    @property
    def has_strobe(self) -> bool:
        return self.has(STROBE) or self.has(STROBE_EFFECT)


BUILTIN_PROFILES: dict[str, FixtureProfile] = {
    name: FixtureProfile(name, channels)
    for name, channels in {
        "rgb": (RED, GREEN, BLUE),
        "rgbw": (RED, GREEN, BLUE, WHITE),
        "dim_rgb": (DIMMER, RED, GREEN, BLUE),
        "dim_rgbw": (DIMMER, RED, GREEN, BLUE, WHITE),
        "rgb_strobe": (RED, GREEN, BLUE, STROBE),
        "dim_rgbw_strobe": (DIMMER, RED, GREEN, BLUE, WHITE, STROBE),
    }.items()
} | _jolt_bar_fx2_profiles()


@dataclass(frozen=True)
class Fixture:
    name: str
    profile: FixtureProfile
    address: int  # 1-based DMX start address
    position: tuple[float, float] = (0.0, 0.0)

    @property
    def has_strobe(self) -> bool:
        return self.profile.has_strobe


@dataclass
class FixtureState:
    rgb: RGB = BLACK
    intensity: float = 1.0
    strobe: float = 0.0  # 0 = off, otherwise strobe rate 0..1
    zones: tuple[RGB, ...] = ()  # per-zone colors for zoned fixtures; empty = all zones show `rgb`


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
        profiles = dict(BUILTIN_PROFILES)
        profiles.update({name: FixtureProfile(name, pc.channels, pc.zone_rows) for name, pc in cfg.profiles.items()})
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
            values = self._channel_values(fixture.profile, state)
            for offset, name in enumerate(fixture.profile.channels):
                universe[fixture.address - 1 + offset] = _byte(values.get(name, 0.0))
        return bytes(universe)

    @staticmethod
    def _channel_values(profile: FixtureProfile, state: FixtureState) -> dict[str, float]:
        intensity = clamp01(state.intensity)
        has_dimmer = profile.has(DIMMER)
        scale = 1.0 if has_dimmer else intensity  # no dimmer channel: fold intensity into color
        values: dict[str, float] = {}
        if has_dimmer:
            values.update(_dimmer(DIMMER, DIMMER_FINE, intensity, profile))

        # only pull white out of the color when the fixture has somewhere to put it
        values[RED], values[GREEN], values[BLUE] = _scaled(state.rgb, scale)
        if profile.has(WHITE) or profile.has(INNER_DIMMER):
            values[RED], values[GREEN], values[BLUE], values[WHITE] = rgb_to_rgbw(_scaled(state.rgb, scale))
        if profile.has(INNER_DIMMER):
            values.update(_dimmer(INNER_DIMMER, INNER_DIMMER_FINE, rgb_to_rgbw(state.rgb)[3] * intensity, profile))

        n = profile.rgb_zones
        if n:
            colors = state.zones if len(state.zones) == n else (state.rgb,) * n
            zoned_white = bool(profile.white_zones or profile.white_groups)
            zones = [rgb_to_rgbw(_scaled(c, scale)) if zoned_white else (*_scaled(c, scale), 0.0) for c in colors]
            for i, (zr, zg, zb, _) in enumerate(zones, 1):
                values[f"{RED}:{i}"], values[f"{GREEN}:{i}"], values[f"{BLUE}:{i}"] = zr, zg, zb
            for role, count in ((WHITE, profile.white_zones), (WHITE_GROUP, profile.white_groups)):
                for j in range(1, count + 1):
                    values[f"{role}:{j}"] = zones[_zone_for(j, count, profile.zones_per_row)][3]

        if profile.has(STROBE):
            values[STROBE] = state.strobe
        if profile.has(STROBE_EFFECT):
            values[STROBE_EFFECT] = (STROBE_EFFECT_STROBE if state.strobe > 0 else STROBE_EFFECT_OPEN) / 255
            values[STROBE_RATE] = values[STROBE_DURATION] = state.strobe
        return values


def _scaled(c: RGB, k: float) -> RGB:
    return (c[0] * k, c[1] * k, c[2] * k)


def _dimmer(coarse: str, fine: str, level: float, profile: FixtureProfile) -> dict[str, float]:
    if not profile.has(fine):
        return {coarse: level}
    hi, lo = divmod(int(round(clamp01(level) * 65535)), 256)
    return {coarse: hi / 255, fine: lo / 255}


def _zone_for(j: int, count: int, per_row: int) -> int:
    """First-row RGB zone (0-based) at the center of white zone/group j (1-based) of `count`."""
    return min(per_row - 1, int((j - 0.5) * per_row / count))


def _byte(x: float) -> int:
    return int(round(clamp01(x) * 255))
