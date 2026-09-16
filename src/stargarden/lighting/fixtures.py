"""Fixture types, DMX modes, cells, and the patch — and rendering of per-cell
state into a DMX universe.

Vocabulary follows GDTF and Eos (see docs/lighting-concepts.md): a fixture type
has DMX modes; a mode has cells (the fixture's light-emitting sub-units, each
with a position and a kind) and DMX channels, each carrying one attribute on
either a cell or a parent geometry — a master. The engine sets attribute values
per cell; rendering resolves masters with Eos's "mastered cells" rule (a master
channel carries the brightest cell's level, cell channels are written relative
to it), so a fixture whose whites share one 16-bit dimmer fades smoothly while a
single lit cell still reaches full output.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from ..config import ConfigError, FixtureConfig, LightingConfig
from .color import BLACK, RGB, clamp01, rgb_to_rgbw

UNIVERSE_SIZE = 512
ROOT = "root"  # the geometry above every cell


class CellKind(StrEnum):
    COLOR = "color"  # additive RGB(W) mixing
    WHITE = "white"  # a plain white emitter, driven by its intensity alone


class Attribute(StrEnum):
    """GDTF attribute names. Channels with any other attribute render as 0."""

    DIMMER = "Dimmer"
    COLOR_ADD_R = "ColorAdd_R"
    COLOR_ADD_G = "ColorAdd_G"
    COLOR_ADD_B = "ColorAdd_B"
    COLOR_ADD_W = "ColorAdd_W"
    COLOR_ADD_CW = "ColorAdd_CW"
    SHUTTER1 = "Shutter1"
    STROBE_FREQUENCY = "StrobeFrequency"
    STROBE_DURATION = "StrobeDuration"
    NO_FEATURE = "NoFeature"


RGB_ATTRIBUTES = (Attribute.COLOR_ADD_R, Attribute.COLOR_ADD_G, Attribute.COLOR_ADD_B)
WHITE_ATTRIBUTES = (Attribute.COLOR_ADD_W, Attribute.COLOR_ADD_CW)
STROBE_ATTRIBUTES = (Attribute.STROBE_FREQUENCY, Attribute.STROBE_DURATION)

# Shutter1 channel functions the engine drives; strobe-in-range gives the rate.
OPEN, STROBE = "Open", "Strobe"


@dataclass(frozen=True)
class ChannelFunction:
    name: str
    dmx_from: int
    dmx_to: int


@dataclass(frozen=True)
class DMXChannel:
    offsets: tuple[int, ...]  # 1-based offsets within the footprint; two = coarse + fine
    attribute: str
    geometry: str = ROOT  # a cell name, a cell's parent, or ROOT
    functions: tuple[ChannelFunction, ...] = ()  # empty: continuous 0..1 over the full range
    name: str = ""  # the manufacturer's label, for reference


@dataclass(frozen=True)
class Cell:
    name: str
    kind: CellKind
    position: tuple[float, float] = (0.5, 0.5)  # in the fixture's unit square, (0, 0) top left
    parent: str = ROOT


@dataclass(frozen=True)
class DMXMode:
    name: str
    footprint: int
    cells: tuple[Cell, ...]
    channels: tuple[DMXChannel, ...]

    def __post_init__(self) -> None:
        used: set[int] = set()
        geometries = {ROOT} | {c.name for c in self.cells} | {c.parent for c in self.cells}
        for ch in self.channels:
            for off in ch.offsets:
                if not 1 <= off <= self.footprint or off in used:
                    raise ValueError(f"mode {self.name!r}: bad or duplicate offset {off} on {ch.attribute}")
                used.add(off)
            if ch.geometry not in geometries:
                raise ValueError(f"mode {self.name!r}: unknown geometry {ch.geometry!r} on {ch.attribute}")

    @property
    def color_cells(self) -> tuple[Cell, ...]:
        return tuple(c for c in self.cells if c.kind is CellKind.COLOR)

    @property
    def white_cells(self) -> tuple[Cell, ...]:
        return tuple(c for c in self.cells if c.kind is CellKind.WHITE)

    @property
    def can_flash(self) -> bool:
        """Usable for lightning: white emitters to pulse, or a shutter to strobe the color."""
        return bool(self.white_cells) or any(ch.attribute == Attribute.SHUTTER1 for ch in self.channels)

    def governed(self, geometry: str) -> tuple[Cell, ...]:
        if geometry == ROOT:
            return self.cells
        return tuple(c for c in self.cells if c.name == geometry or c.parent == geometry)

    def channel(self, attribute: str, geometry: str) -> DMXChannel | None:
        return next((ch for ch in self.channels if ch.attribute == attribute and ch.geometry == geometry), None)


@dataclass(frozen=True)
class FixtureType:
    name: str
    modes: dict[str, DMXMode]

    def mode(self, name: str) -> DMXMode:
        if not name:
            if len(self.modes) == 1:
                return next(iter(self.modes.values()))
            raise ConfigError(f"fixture type {self.name!r} has modes {sorted(self.modes)}; pick one with `mode`")
        if name not in self.modes:
            raise ConfigError(f"fixture type {self.name!r} has no mode {name!r} (have {sorted(self.modes)})")
        return self.modes[name]


@dataclass
class CellState:
    """What the engine wants from one cell. For white cells `intensity` is the white level."""

    color: RGB = BLACK
    intensity: float = 1.0
    strobe: float = 0.0  # 0 = shutter open, else strobe rate 0..1


FixtureFrame = dict[str, CellState]  # cell name → state


# -- building modes -----------------------------------------------------------

SIMPLE_ROLES = {
    "red": Attribute.COLOR_ADD_R,
    "green": Attribute.COLOR_ADD_G,
    "blue": Attribute.COLOR_ADD_B,
    "white": Attribute.COLOR_ADD_W,
    "dimmer": Attribute.DIMMER,
    "dimmer_fine": Attribute.DIMMER,
    "strobe": Attribute.SHUTTER1,
}
SINGLE_CHANNEL_STROBE = (ChannelFunction(OPEN, 0, 0), ChannelFunction(STROBE, 1, 255))
CELL = "cell"


def simple_mode(name: str, roles: tuple[str, ...]) -> DMXMode:
    """A one-cell fixture from a list of channel roles: red/green/blue/white on the
    cell, dimmer (+ dimmer_fine) and strobe on the master; anything else is unused."""
    channels: list[DMXChannel] = []
    for offset, role in enumerate(roles, 1):
        attribute = SIMPLE_ROLES.get(role, Attribute.NO_FEATURE)
        if role == "dimmer_fine":
            coarse = next((ch for ch in channels if ch.attribute == Attribute.DIMMER), None)
            if coarse is None:
                raise ConfigError(f"mode {name!r}: dimmer_fine without a dimmer before it")
            channels[channels.index(coarse)] = DMXChannel((*coarse.offsets, offset), Attribute.DIMMER, name=role)
            continue
        if attribute in RGB_ATTRIBUTES or attribute in WHITE_ATTRIBUTES:
            channels.append(DMXChannel((offset,), attribute, CELL, name=role))
        elif attribute == Attribute.SHUTTER1:
            channels.append(DMXChannel((offset,), attribute, functions=SINGLE_CHANNEL_STROBE, name=role))
        else:
            channels.append(DMXChannel((offset,), attribute, name=role))
    return DMXMode(name, len(roles), (Cell(CELL, CellKind.COLOR),), tuple(channels))


GENERIC = FixtureType(
    "generic",
    {
        name: simple_mode(name, roles)
        for name, roles in {
            "rgb": ("red", "green", "blue"),
            "rgbw": ("red", "green", "blue", "white"),
            "dim_rgb": ("dimmer", "red", "green", "blue"),
            "dim_rgbw": ("dimmer", "red", "green", "blue", "white"),
            "rgb_strobe": ("red", "green", "blue", "strobe"),
            "dim_rgbw_strobe": ("dimmer", "red", "green", "blue", "white", "strobe"),
        }.items()
    },
)


class ModeBuilder:
    """Appends channels in DMX order, tracking the footprint."""

    def __init__(self) -> None:
        self.channels: list[DMXChannel] = []
        self._next = 1

    def add(
        self, attribute: str, geometry: str = ROOT, bits: int = 8, functions: tuple[ChannelFunction, ...] = (), name: str = ""
    ) -> ModeBuilder:
        width = bits // 8
        self.channels.append(DMXChannel(tuple(range(self._next, self._next + width)), attribute, geometry, functions, name))
        self._next += width
        return self

    def skip(self, name: str) -> ModeBuilder:
        return self.add(Attribute.NO_FEATURE, name=name)

    def build(self, name: str, cells: tuple[Cell, ...]) -> DMXMode:
        return DMXMode(name, self._next - 1, cells, tuple(self.channels))


# -- ADJ Jolt Bar FX2 -----------------------------------------------------------

_ADJ_SHUTTER = (
    ChannelFunction(OPEN, 0, 2),
    ChannelFunction(STROBE, 3, 5),
    ChannelFunction("RampUp", 6, 50),
    ChannelFunction("RampDown", 51, 100),
    ChannelFunction("RampUpDown", 101, 150),
    ChannelFunction("Lightning", 151, 200),
    ChannelFunction("Random", 201, 255),
)
_RGB, _WHITE = "rgb", "white"  # the bar's two geometries: outer RGB rows, inner white row


def _jolt_cells(rgb: int, white: int) -> tuple[Cell, ...]:
    """The bar is three rows of 16: RGB zones along the top row then the bottom
    row (zone n/2+1 sits under zone 1), cool-white zones in the middle row."""
    cells = []
    per_row = max(1, rgb // 2)
    for i in range(rgb):
        x, y = ((i % per_row) + 0.5) / per_row, (0.2 if i < per_row else 0.8)
        cells.append(Cell(f"rgb{i + 1}", CellKind.COLOR, (x, y) if rgb > 1 else (0.5, 0.5), _RGB))
    for j in range(white):
        cells.append(Cell(f"w{j + 1}", CellKind.WHITE, ((j + 0.5) / white, 0.5), _WHITE))
    return tuple(cells)


def _jolt_bar_fx2() -> FixtureType:
    """ADJ Jolt Bar FX2, all 17 DMX modes (ADJ "DMX Traits" sheet / manual JOL286;
    cross-checked against the Lightkey profile in docs/fixtures/).

    Modes differ in how many zones are exposed and which control blocks come
    along: a shutter/strobe trio, program and color macros (parked at 0), CT
    presets + green shift (parked at 0), and in the bigger modes a second
    dimmer/strobe block for the whites. In 18/20CH there is no white channel at
    all: the white dimmer is the only white control. In 78/80CH the four "Inner
    White Group" channels sit next to 16 per-zone whites; they follow the white
    level (harmless whether they are masters or additive). Select the mode on the
    fixture's menu; the mode name says which.
    """

    def rgb(b: ModeBuilder, n: int) -> ModeBuilder:
        for i in range(1, n + 1):
            for attr in RGB_ATTRIBUTES:
                b.add(attr, f"rgb{i}", name=f"{attr.removeprefix('ColorAdd_')} {i}")
        return b

    def cw(b: ModeBuilder, n: int, label: str = "White") -> ModeBuilder:
        for j in range(1, n + 1):
            b.add(Attribute.COLOR_ADD_CW, f"w{j}", name=f"{label} {j}")
        return b

    def dimmer(b: ModeBuilder, geometry: str) -> ModeBuilder:
        return b.add(Attribute.DIMMER, geometry, bits=16, name="Dimmer")

    def shutter(b: ModeBuilder, geometry: str) -> ModeBuilder:
        b.add(Attribute.SHUTTER1, geometry, functions=_ADJ_SHUTTER, name="Strobe Effect")
        b.add(Attribute.STROBE_FREQUENCY, geometry, name="Strobe Rate")
        return b.add(Attribute.STROBE_DURATION, geometry, name="Strobe Duration")

    def program(b: ModeBuilder, label: str) -> ModeBuilder:
        return b.skip(f"{label} Program Macro").skip(f"{label} Program Macro Speed")

    def groups(b: ModeBuilder) -> ModeBuilder:  # 78/80CH: group channels beside per-zone whites
        for j in range(1, 5):
            b.add(Attribute.COLOR_ADD_CW, _WHITE, name=f"Inner White Group {j}")
        return b

    def ct(b: ModeBuilder) -> ModeBuilder:
        return b.skip("CT Presets").skip("Green Shift")

    modes: dict[str, DMXMode] = {}

    def mode(n: int, rgb_cells: int, white_cells: int, build) -> None:
        b = ModeBuilder()
        build(b)
        modes[f"{n}ch"] = b.build(f"{n}ch", _jolt_cells(rgb_cells, white_cells))

    mode(6, 1, 1, lambda b: dimmer(cw(rgb(b, 1), 1, "Inner White"), ROOT))
    mode(9, 1, 1, lambda b: shutter(dimmer(cw(rgb(b, 1), 1, "Inner White"), ROOT), ROOT))
    mode(
        13,
        1,
        1,
        lambda b: (
            shutter(dimmer(cw(rgb(b, 1), 1, "Inner White").skip("Outer Color Macros"), ROOT), ROOT)
            .skip("Outer Program Macro")
            .skip("Inner Program Macro")
            .skip("In/Out Program Macro Speed")
        ),
    )
    mode(16, 4, 4, lambda b: cw(rgb(b, 4), 4))
    mode(
        18,
        1,
        1,
        lambda b: program(
            shutter(dimmer(program(shutter(dimmer(rgb(b, 1).skip("Outer Color Macros"), _RGB), _RGB), "Outer"), _WHITE), _WHITE), "Inner"
        ),
    )
    mode(
        20,
        1,
        1,
        lambda b: program(
            shutter(dimmer(program(shutter(dimmer(ct(rgb(b, 1)).skip("Outer Color Macros"), _RGB), _RGB), "Outer"), _WHITE), _WHITE),
            "Inner",
        ),
    )
    mode(32, 8, 8, lambda b: cw(rgb(b, 8), 8))
    mode(34, 8, 8, lambda b: cw(ct(rgb(b, 8)), 8))
    mode(38, 8, 4, lambda b: shutter(dimmer(cw(shutter(dimmer(rgb(b, 8), _RGB), _RGB), 4, "Inner White Group"), _WHITE), _WHITE))
    mode(
        43,
        8,
        4,
        lambda b: program(
            shutter(
                dimmer(
                    cw(program(shutter(dimmer(rgb(b, 8).skip("Outer Color Macros"), _RGB), _RGB), "Outer"), 4, "Inner White Group"), _WHITE
                ),
                _WHITE,
            ),
            "Inner",
        ),
    )
    mode(
        45,
        8,
        4,
        lambda b: program(
            shutter(
                dimmer(
                    cw(program(shutter(dimmer(ct(rgb(b, 8)).skip("Outer Color Macros"), _RGB), _RGB), "Outer"), 4, "Inner White Group"),
                    _WHITE,
                ),
                _WHITE,
            ),
            "Inner",
        ),
    )
    mode(64, 16, 16, lambda b: cw(rgb(b, 16), 16))
    mode(78, 16, 16, lambda b: shutter(dimmer(groups(shutter(dimmer(cw(rgb(b, 16), 16), _RGB), _RGB)), _WHITE), _WHITE))
    mode(80, 16, 16, lambda b: shutter(dimmer(groups(shutter(dimmer(cw(ct(rgb(b, 16)), 16), _RGB), _RGB)), _WHITE), _WHITE))
    mode(112, 32, 16, lambda b: cw(rgb(b, 32), 16))
    mode(
        127,
        32,
        16,
        lambda b: program(
            shutter(dimmer(cw(program(shutter(dimmer(rgb(b, 32).skip("Outer Color Macros"), _RGB), _RGB), "Outer"), 16), _WHITE), _WHITE),
            "Inner",
        ),
    )
    mode(
        129,
        32,
        16,
        lambda b: program(
            shutter(
                dimmer(cw(program(shutter(dimmer(ct(rgb(b, 32)).skip("Outer Color Macros"), _RGB), _RGB), "Outer"), 16), _WHITE), _WHITE
            ),
            "Inner",
        ),
    )
    return FixtureType("jolt_bar_fx2", modes)


BUILTIN_TYPES: dict[str, FixtureType] = {t.name: t for t in (GENERIC, _jolt_bar_fx2())}


# -- patch and rendering ----------------------------------------------------------


@dataclass(frozen=True)
class Fixture:
    name: str
    fixture_type: FixtureType
    mode: DMXMode
    address: int  # 1-based DMX start address
    position: tuple[float, float] = (0.0, 0.0)


@dataclass
class Patch:
    fixtures: tuple[Fixture, ...]
    _resolvers: dict[str, _Resolver] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        used: dict[int, str] = {}
        for f in self.fixtures:
            last = f.address + f.mode.footprint - 1
            if f.address < 1 or last > UNIVERSE_SIZE:
                raise ConfigError(f"fixture {f.name!r}: address {f.address} out of range for {f.fixture_type.name} {f.mode.name}")
            for ch in range(f.address, last + 1):
                if ch in used:
                    raise ConfigError(f"fixture {f.name!r} overlaps {used[ch]!r} at channel {ch}")
                used[ch] = f.name
            self._resolvers.setdefault(f"{f.fixture_type.name}/{f.mode.name}", _Resolver(f.mode))

    @classmethod
    def from_config(cls, cfg: LightingConfig) -> Patch:
        types = dict(BUILTIN_TYPES)
        types.update({name: FixtureType(name, {"default": simple_mode("default", pc.channels)}) for name, pc in cfg.profiles.items()})
        return cls(tuple(cls._fixture(types, fc) for fc in cfg.fixtures))

    @staticmethod
    def _fixture(types: dict[str, FixtureType], fc: FixtureConfig) -> Fixture:
        if fc.type not in types:
            raise ConfigError(f"fixture {fc.name!r}: unknown fixture type {fc.type!r}")
        fixture_type = types[fc.type]
        return Fixture(fc.name, fixture_type, fixture_type.mode(fc.mode), fc.address, fc.position)

    def __len__(self) -> int:
        return len(self.fixtures)

    @property
    def can_flash(self) -> bool:
        return any(f.mode.can_flash for f in self.fixtures)

    def render(self, frames: list[FixtureFrame]) -> bytes:
        universe = bytearray(UNIVERSE_SIZE)
        for fixture, frame in zip(self.fixtures, frames, strict=True):
            resolver = self._resolvers[f"{fixture.fixture_type.name}/{fixture.mode.name}"]
            for offset, value in resolver.resolve(frame):
                universe[fixture.address - 1 + offset - 1] = value
        return bytes(universe)


class _Resolver:
    """Turns a fixture frame into (offset, byte) pairs for one DMX mode."""

    def __init__(self, mode: DMXMode) -> None:
        self.mode = mode
        # nearest Dimmer channel above each cell (its parent's, else root's), and whether it has its own
        self._master_dimmer: dict[str, DMXChannel | None] = {}
        self._own_dimmer: set[str] = set()
        self._mixing_white: set[str] = set()
        for cell in mode.cells:
            self._master_dimmer[cell.name] = mode.channel(Attribute.DIMMER, cell.parent) or mode.channel(Attribute.DIMMER, ROOT)
            if mode.channel(Attribute.DIMMER, cell.name):
                self._own_dimmer.add(cell.name)
            if cell.kind is CellKind.COLOR and any(mode.channel(a, cell.name) for a in WHITE_ATTRIBUTES):
                self._mixing_white.add(cell.name)
        self._cells = {c.name: c for c in mode.cells}

    def resolve(self, frame: FixtureFrame) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for ch in self.mode.channels:
            level, function = self._value(ch, frame)
            out.extend(_encode(ch, level, function))
        return out

    def _relative(self, name: str, frame: FixtureFrame) -> float:
        """A cell's level relative to its master dimmer (Eos "mastered cells")."""
        intensity = clamp01(frame[name].intensity)
        master = self._master_dimmer[name]
        if master is None:
            return intensity
        top = max(clamp01(frame[c.name].intensity) for c in self.mode.governed(master.geometry))
        return intensity / top if top > 0 else 0.0

    def _cell_scale(self, name: str, frame: FixtureFrame) -> float:
        return 1.0 if name in self._own_dimmer else self._relative(name, frame)

    def _value(self, ch: DMXChannel, frame: FixtureFrame) -> tuple[float, str | None]:
        attr = ch.attribute
        cells = self.mode.governed(ch.geometry)
        if attr == Attribute.DIMMER:
            if ch.geometry in self._cells:
                return self._relative(ch.geometry, frame), None
            return max((clamp01(frame[c.name].intensity) for c in cells), default=0.0), None
        if attr in RGB_ATTRIBUTES or attr in WHITE_ATTRIBUTES:
            if ch.geometry in self._cells:
                return self._emitter(self._cells[ch.geometry], attr, frame), None
            return max((self._emitter(c, attr, frame) for c in cells), default=0.0), None
        if attr == Attribute.SHUTTER1:
            strobe = max((clamp01(frame[c.name].strobe) for c in cells), default=0.0)
            return (strobe, STROBE) if strobe > 0 else (0.0, OPEN)
        if attr in STROBE_ATTRIBUTES:
            return max((clamp01(frame[c.name].strobe) for c in cells), default=0.0), None
        return 0.0, None

    def _emitter(self, cell: Cell, attr: str, frame: FixtureFrame) -> float:
        scale = self._cell_scale(cell.name, frame)
        if cell.kind is CellKind.WHITE:
            return scale if attr in WHITE_ATTRIBUTES else 0.0
        r, g, b = (clamp01(c * scale) for c in frame[cell.name].color)
        if cell.name in self._mixing_white:
            r, g, b, w = rgb_to_rgbw((r, g, b))
        else:
            w = 0.0
        return {Attribute.COLOR_ADD_R: r, Attribute.COLOR_ADD_G: g, Attribute.COLOR_ADD_B: b}.get(
            attr, w if attr in WHITE_ATTRIBUTES else 0.0
        )


def _encode(ch: DMXChannel, level: float, function: str | None) -> list[tuple[int, int]]:
    level = clamp01(level)
    if ch.functions:
        fn = next((f for f in ch.functions if f.name == function), ch.functions[0])
        return [(ch.offsets[0], fn.dmx_from + int(round(level * (fn.dmx_to - fn.dmx_from))))]
    full = int(round(level * (2 ** (8 * len(ch.offsets)) - 1)))
    return [(off, (full >> (8 * (len(ch.offsets) - 1 - i))) & 0xFF) for i, off in enumerate(ch.offsets)]
