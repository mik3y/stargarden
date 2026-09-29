"""Program configuration: a TOML file mapped onto frozen dataclasses.

Every section has sensible defaults so a dev config can be tiny; unknown keys
are rejected so typos surface at startup rather than as silently-ignored
settings in the field.
"""

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    pass


class AudioMode(StrEnum):
    QUAD = "quad"
    STEREO = "stereo"


class SensorRole(StrEnum):
    PLATFORM = "platform"
    WALKWAY = "walkway"


@dataclass(frozen=True)
class SiteConfig:
    name: str = "Stargarden"
    latitude: float = 0.0
    longitude: float = 0.0
    timezone: str = "UTC"


@dataclass(frozen=True)
class ScheduleConfig:
    enabled: bool = True
    sunset_offset_min: float = 20.0
    sunrise_offset_min: float = -30.0


@dataclass(frozen=True)
class TimersConfig:
    show_delay_s: float = 600.0
    show_repeat_delay_s: float = 900.0
    lights_out_s: float = 4.0
    ambient_theme_rotation_s: float = 1200.0


@dataclass(frozen=True)
class AudioLevels:
    bed: float = 0.8
    discretes: float = 0.7
    music: float = 0.9


QUAD_CORNERS: tuple[tuple[float, float], ...] = ((-1.0, 1.0), (1.0, 1.0), (-1.0, -1.0), (1.0, -1.0))  # FL, FR, RL, RR


@dataclass(frozen=True)
class AudioConfig:
    backend: str = "auto"  # auto | sounddevice | null
    device: str | int | None = None
    mode: AudioMode = AudioMode.QUAD
    samplerate: int = 48000
    blocksize: int = 1024
    # where each output channel's speaker stands, in the same compass square as fixture
    # positions (x: -1 left … 1 right, y: -1 rear … 1 front); reorder to match the cabling
    speakers: tuple[tuple[float, float], ...] = QUAD_CORNERS
    # which of the device's output channels (1-based) carry outputs 1-4; a 7.1 card has its
    # front pair on 1-2 and its surround pair on 5-6, a 4-out interface is simply 1-4
    channel_map: tuple[int, ...] = (1, 2, 3, 4)
    levels: AudioLevels = field(default_factory=AudioLevels)
    duck_level: float = 0.25
    duck_fade_s: float = 3.0
    bed_crossfade_s: float = 8.0


@dataclass(frozen=True)
class DiscretesConfig:
    min_interval_s: float = 25.0
    max_interval_s: float = 120.0


@dataclass(frozen=True)
class FixtureConfig:
    name: str
    type: str  # a built-in fixture type ("generic", "jolt_bar_fx2") or a [lighting.profiles.*] name
    address: int
    mode: str = ""  # DMX mode of the type; may be omitted when the type has only one
    position: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class LightningConfig:
    enabled: bool = True
    mean_interval_s: float = 1200.0  # strikes arrive at random, this far apart on average
    min_interval_s: float = 300.0
    states: tuple[str, ...] = ("presence",)  # program states in which lightning may strike
    thunder_delay_s: tuple[float, float] = (0.3, 2.5)  # flash → thunder; a short delay is a close strike


@dataclass(frozen=True)
class ProfileConfig:
    """A simple one-cell fixture type declared in config as a list of channel roles."""

    channels: tuple[str, ...]


@dataclass(frozen=True)
class LightingConfig:
    driver: str = "console"  # console | null | enttec_open | enttec_pro
    port: str = "auto"  # serial device, or "auto" to pick the first FTDI widget
    fps: float = 30.0
    peak: float = 1.0  # ceiling on theme brightness (0..1); lightning is exempt. Adjustable live from the console
    fixtures: tuple[FixtureConfig, ...] = ()
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class SensorConfig:
    role: SensorRole
    address: str
    name: str = ""


@dataclass(frozen=True)
class PresenceConfig:
    source: str = "simulated"  # simulated | ble
    vacancy_timeout_s: float = 900.0
    sensors: tuple[SensorConfig, ...] = ()


@dataclass(frozen=True)
class WebConfig:
    """The web console (`web.py`): the browser twin of the TUI."""

    enabled: bool = True
    host: str = "127.0.0.1"  # "0.0.0.0" to reach it from other machines on the site network
    port: int = 7710


@dataclass(frozen=True)
class Config:
    path: Path
    assets_root: Path
    site: SiteConfig = field(default_factory=SiteConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    timers: TimersConfig = field(default_factory=TimersConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    discretes: DiscretesConfig = field(default_factory=DiscretesConfig)
    lighting: LightingConfig = field(default_factory=LightingConfig)
    lightning: LightningConfig = field(default_factory=LightningConfig)
    presence: PresenceConfig = field(default_factory=PresenceConfig)
    web: WebConfig = field(default_factory=WebConfig)


def _coerce(kind: Any, value: Any, where: str) -> Any:
    if isinstance(kind, type) and issubclass(kind, StrEnum):
        try:
            return kind(value)
        except ValueError:
            raise ConfigError(f"{where}: expected one of {[m.value for m in kind]}, got {value!r}") from None
    if kind is Path:
        return Path(value)
    if kind is float and isinstance(value, bool):
        raise ConfigError(f"{where}: expected a number")
    if kind is float and isinstance(value, int):
        return float(value)
    if kind in (float, int, str, bool) and not isinstance(value, kind):
        raise ConfigError(f"{where}: expected {kind.__name__}, got {value!r}")
    if kind == tuple[float, float]:
        if not (isinstance(value, list) and len(value) == 2):
            raise ConfigError(f"{where}: expected [x, y]")
        return (float(value[0]), float(value[1]))
    if kind == tuple[str, ...]:
        return tuple(str(v) for v in value)
    if kind == tuple[int, ...]:
        if not isinstance(value, list) or not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
            raise ConfigError(f"{where}: expected a list of integers")
        return tuple(value)
    if kind == tuple[tuple[float, float], ...]:
        return tuple(_coerce(tuple[float, float], v, f"{where}[{i}]") for i, v in enumerate(value))
    if is_dataclass(kind) and isinstance(value, dict):
        return _fill(kind, value, where)
    return value


def _fill(cls: type, data: dict[str, Any], where: str) -> Any:
    """Build dataclass `cls` from a TOML table, rejecting unknown keys."""
    names = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - names)
    if unknown:
        raise ConfigError(f"{where}: unknown keys {unknown}")
    kwargs = {}
    for f in fields(cls):
        if f.name in data:
            kwargs[f.name] = _coerce(f.type, data[f.name], f"{where}.{f.name}")
    try:
        return cls(**kwargs)
    except TypeError as e:
        raise ConfigError(f"{where}: {e}") from None


def _table_list(cls: type, items: Any, where: str) -> tuple:
    if not isinstance(items, list):
        raise ConfigError(f"{where}: expected an array of tables")
    return tuple(_fill(cls, item, f"{where}[{i}]") for i, item in enumerate(items))


def load_config(path: Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    known = {"site", "schedule", "timers", "audio", "discretes", "lighting", "lightning", "presence", "web", "assets"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"{path}: unknown sections {unknown}")

    lighting_raw = dict(raw.get("lighting", {}))
    fixtures = _table_list(FixtureConfig, lighting_raw.pop("fixtures", []), "lighting.fixtures")
    profiles = {name: _fill(ProfileConfig, spec, f"lighting.profiles.{name}") for name, spec in lighting_raw.pop("profiles", {}).items()}
    lighting = replace(_fill(LightingConfig, lighting_raw, "lighting"), fixtures=fixtures, profiles=profiles)
    if not 0.0 <= lighting.peak <= 1.0:
        raise ConfigError(f"lighting.peak: expected 0..1, got {lighting.peak}")

    presence_raw = dict(raw.get("presence", {}))
    sensors = _table_list(SensorConfig, presence_raw.pop("sensors", []), "presence.sensors")
    presence = replace(_fill(PresenceConfig, presence_raw, "presence"), sensors=sensors)

    audio = _fill(AudioConfig, raw.get("audio", {}), "audio")
    if len(audio.channel_map) != 4 or len(set(audio.channel_map)) != 4 or min(audio.channel_map) < 1:
        raise ConfigError(f"audio.channel_map: expected four distinct output channels numbered from 1, got {list(audio.channel_map)}")

    assets_raw = raw.get("assets", {})
    root = Path(assets_raw.get("root", "assets")).expanduser()  # "~/stargarden-assets" works for any service user
    if not root.is_absolute():
        root = path.parent / root

    return Config(
        path=path,
        assets_root=root,
        site=_fill(SiteConfig, raw.get("site", {}), "site"),
        schedule=_fill(ScheduleConfig, raw.get("schedule", {}), "schedule"),
        timers=_fill(TimersConfig, raw.get("timers", {}), "timers"),
        audio=audio,
        discretes=_fill(DiscretesConfig, raw.get("discretes", {}), "discretes"),
        lighting=lighting,
        lightning=_fill(LightningConfig, raw.get("lightning", {}), "lightning"),
        presence=presence,
        web=_fill(WebConfig, raw.get("web", {}), "web"),
    )
