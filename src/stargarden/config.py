"""Program configuration: a TOML file mapped onto frozen dataclasses.

Every section has sensible defaults so a dev config can be tiny; unknown keys
are rejected so typos surface at startup rather than as silently-ignored
settings in the field.
"""

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

MIN_LEG_S, MAX_LEG_S = 10.0, 24 * 3600.0  # bounds on the sunset's length
MIN_DUSK_LEVEL = 0.05  # the purple end dims but never goes black


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class SiteConfig:
    name: str = "Stargarden"


@dataclass(frozen=True)
class SunsetConfig:
    """The defaults a console can change live: the change persists over these."""

    leg_s: float = 900.0  # orange to purple; the way back takes the same
    dusk_level: float = 0.35  # brightness at the purple end, relative to the orange end


@dataclass(frozen=True)
class FixtureConfig:
    name: str
    type: str  # a built-in fixture type ("generic", "jolt_bar_fx2") or a [lighting.profiles.*] name
    address: int
    mode: str = ""  # DMX mode of the type; may be omitted when the type has only one
    position: tuple[float, float] = (0.0, 0.0)


@dataclass(frozen=True)
class ProfileConfig:
    """A simple one-cell fixture type declared in config as a list of channel roles."""

    channels: tuple[str, ...]


@dataclass(frozen=True)
class LightingConfig:
    driver: str = "console"  # console | null | enttec_open | enttec_pro
    port: str = "auto"  # serial device, or "auto" to pick the first FTDI widget
    fps: float = 30.0
    peak: float = 1.0  # ceiling on brightness (0..1). Adjustable live from the console
    fixtures: tuple[FixtureConfig, ...] = ()
    profiles: dict[str, ProfileConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class WebConfig:
    """The web console (`web.py`)."""

    enabled: bool = True
    host: str = "127.0.0.1"  # "0.0.0.0" to reach it from other machines on the site network
    port: int = 7710


@dataclass(frozen=True)
class StateConfig:
    """Where console overrides persist, outside the code directory."""

    path: Path = Path("~/.local/state/stargarden/state.json")


@dataclass(frozen=True)
class Config:
    path: Path
    site: SiteConfig = field(default_factory=SiteConfig)
    sunset: SunsetConfig = field(default_factory=SunsetConfig)
    lighting: LightingConfig = field(default_factory=LightingConfig)
    web: WebConfig = field(default_factory=WebConfig)
    state: StateConfig = field(default_factory=StateConfig)


def _coerce(kind: Any, value: Any, where: str) -> Any:
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
    known = {"site", "sunset", "lighting", "web", "state"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"{path}: unknown sections {unknown}")

    lighting_raw = dict(raw.get("lighting", {}))
    fixtures = _table_list(FixtureConfig, lighting_raw.pop("fixtures", []), "lighting.fixtures")
    profiles = {name: _fill(ProfileConfig, spec, f"lighting.profiles.{name}") for name, spec in lighting_raw.pop("profiles", {}).items()}
    lighting = replace(_fill(LightingConfig, lighting_raw, "lighting"), fixtures=fixtures, profiles=profiles)
    if not 0.0 <= lighting.peak <= 1.0:
        raise ConfigError(f"lighting.peak: expected 0..1, got {lighting.peak}")

    sunset = _fill(SunsetConfig, raw.get("sunset", {}), "sunset")
    if not MIN_LEG_S <= sunset.leg_s <= MAX_LEG_S:
        raise ConfigError(f"sunset.leg_s: expected {MIN_LEG_S:g}..{MAX_LEG_S:g}, got {sunset.leg_s}")
    if not MIN_DUSK_LEVEL <= sunset.dusk_level <= 1.0:
        raise ConfigError(f"sunset.dusk_level: expected {MIN_DUSK_LEVEL}..1, got {sunset.dusk_level}")

    state = _fill(StateConfig, raw.get("state", {}), "state")
    state_path = state.path.expanduser()
    if not state_path.is_absolute():
        state_path = path.parent / state_path
    state = replace(state, path=state_path)

    return Config(
        path=path,
        site=_fill(SiteConfig, raw.get("site", {}), "site"),
        sunset=sunset,
        lighting=lighting,
        web=_fill(WebConfig, raw.get("web", {}), "web"),
        state=state,
    )
