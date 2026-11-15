"""The web console's control surface.

What the console shows (a `Status` snapshot, the fixture preview, the log
stream) and what it may do (the `Console` actions) live here. A new control is
added here first, as a field on `Status` or an `@action` method on `Console`,
and `web/` then draws it.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .app import Stargarden
from .config import FixtureRole
from .lighting.color import RGB
from .sunset import color_at, level_at

log = logging.getLogger(__name__)

NUDGE = 0.05  # one press of darker or brighter
PALETTE_STEPS = 21  # swatches along the console's picture of the sunset
LOGGER_PREFIX = "stargarden."
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class ActionError(Exception):
    """A console action was called with arguments it cannot use."""


class UnknownAction(ActionError):
    pass


class LogBuffer(logging.Handler):
    """Ring of recent log records, numbered so that several browsers can each read
    from where they left off. Records arrive from any thread; `since` is safe to
    call from the event loop."""

    def __init__(self, maxlen: int = 500) -> None:
        super().__init__()
        self._records: list[tuple[int, logging.LogRecord]] = []
        self._maxlen = maxlen
        self._next = 0
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        record.getMessage()  # format the arguments now, while they are still valid
        with self._lock:
            self._records.append((self._next, record))
            self._next += 1
            if len(self._records) > self._maxlen:
                del self._records[: len(self._records) - self._maxlen]

    @property
    def next_seq(self) -> int:
        return self._next

    def since(self, seq: int) -> tuple[list[tuple[int, logging.LogRecord]], int]:
        """Records numbered `seq` and later that are still retained, and the sequence
        number to ask for next time."""
        with self._lock:
            return [(s, r) for s, r in self._records if s >= seq], self._next


def install_log_buffer(level: str) -> LogBuffer:
    """Route the root logger into a `LogBuffer` and to stderr."""
    buffer = LogBuffer()
    stream = logging.StreamHandler()
    stream.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [buffer, stream]
    logging.captureWarnings(True)  # Python warnings reach the console too
    return buffer


def record_to_dict(seq: int, record: logging.LogRecord) -> dict[str, Any]:
    """A log record as plain data for the web console."""
    return {
        "seq": seq,
        "t": record.created,
        "level": record.levelname,
        "name": record.name.removeprefix(LOGGER_PREFIX),
        "msg": record.getMessage(),
        "exc": logging.Formatter().formatException(record.exc_info) if record.exc_info else None,
    }


def debug_enabled() -> bool:
    return logging.getLogger().level <= logging.DEBUG


@dataclass(frozen=True)
class Status:
    """Everything the console's panels show, as plain data (JSON-ready)."""

    site: str
    on: bool
    master: float  # the on/off fade, 0..1
    driver: str
    position: float  # the sunset's place, 0 (orange) to 1 (purple)
    shown: float  # the place the lights show, gliding toward `position`
    direction: str  # "darkening" | "brightening"
    paused: bool
    leg_s: float
    leg_remaining_s: float
    peak: float
    dusk_level: float
    palette: list[tuple[int, int, int]]  # the sunset end to end, as it looks at the current dusk level
    program: str  # what the bars show, the sunset or a dance pattern
    programs: list[str]
    tempo: float  # the dance patterns' pace, bpm
    spots: bool  # pin spots are patched
    spot_level: float
    spot_color: str  # "white" | "match"
    debug: bool
    check: bool  # the setup check is walking the fixtures


@dataclass(frozen=True)
class CellPreview:
    name: str  # the cell's name in its fixture mode
    rgb: tuple[int, int, int]
    strobe: bool = False


@dataclass(frozen=True)
class FixturePreview:
    """A fixture's color cells row by row (top first, left to right), and its white
    cells as grey swatches."""

    name: str
    rows: tuple[tuple[CellPreview, ...], ...]
    whites: tuple[CellPreview, ...]


def swatch_rgb(color: RGB, intensity: float, peak: float) -> tuple[int, int, int]:
    """Preview color for a cell, as if the peak were 1.0: a softened rig still shows
    its look in the console rather than a row of black squares."""
    level = min(1.0, intensity / peak if peak > 0 else intensity)  # an overlay's absolute level must not overshoot
    r, g, b = (int(round(255 * min(1.0, ch * level))) for ch in color)
    return r, g, b


def action(fn: Callable) -> Callable:
    """Mark a `Console` method as callable by name (`Console.act`), e.g. from the web API."""
    fn.__console_action__ = True  # type: ignore[attr-defined]
    return fn


class Console:
    """Snapshots of the program for display, and the actions a console may take on it."""

    def __init__(self, program: Stargarden, log_buffer: LogBuffer) -> None:
        self.program = program
        self.log_buffer = log_buffer

    def status(self) -> Status:
        p = self.program
        sunset = p.sunset
        steps = [k / (PALETTE_STEPS - 1) for k in range(PALETTE_STEPS)]
        return Status(
            site=p.config.site.name,
            on=p.on,
            master=p.lighting.master(),
            driver=p.lighting.driver.name,
            position=sunset.position,
            shown=sunset.shown(),
            direction=sunset.direction,
            paused=sunset.paused,
            leg_s=sunset.leg_s,
            leg_remaining_s=sunset.leg_remaining_s,
            peak=p.lighting.peak,
            dusk_level=sunset.dusk_level,
            palette=[swatch_rgb(color_at(u), level_at(u, sunset.dusk_level), 1.0) for u in steps],
            program=p.lighting.program.name,
            programs=list(p.programs),
            tempo=p.lighting.tempo,
            spots=p.has_spots,
            spot_level=p.lighting.spot_level,
            spot_color=p.lighting.spot_color.value,
            debug=debug_enabled(),
            check=p.check.running,
        )

    def fixtures(self) -> list[FixturePreview]:
        p = self.program
        previews = []
        for fixture, frame in zip(p.patch.fixtures, p.lighting.last_frames, strict=True):
            mode = fixture.mode
            peak = p.lighting.peak if fixture.role is FixtureRole.BAR else 1.0
            ys = sorted({c.position[1] for c in mode.color_cells})
            rows = []
            for y in ys:
                cells = sorted((c for c in mode.color_cells if c.position[1] == y), key=lambda c: c.position[0])
                rows.append(
                    tuple(
                        CellPreview(c.name, swatch_rgb(frame[c.name].color, frame[c.name].intensity, peak), frame[c.name].strobe > 0)
                        for c in cells
                    )
                )
            whites = []
            for c in mode.white_cells:
                w = int(round(255 * frame[c.name].intensity))
                whites.append(CellPreview(c.name, (w, w, w)))
            previews.append(FixturePreview(fixture.name, tuple(rows), tuple(whites)))
        return previews

    def act(self, name: str, params: dict[str, Any] | None = None) -> Any:
        """Run the action called `name` with keyword arguments from `params` (JSON-ish
        values; enums are given by value). Bad names or arguments raise `ActionError`."""
        fn = getattr(self, name, None)
        if not callable(fn) or not getattr(fn, "__console_action__", False):
            raise UnknownAction(f"unknown action {name!r}")
        try:
            return fn(**(params or {}))
        except (TypeError, ValueError) as e:
            raise ActionError(f"{name}: {e}") from None

    @action
    def set_on(self, on: bool) -> bool:
        """Fade the lights up or out."""
        if not isinstance(on, bool):
            raise ValueError("on must be true or false")
        self.program.set_on(on)
        return on

    @action
    def toggle_on(self) -> bool:
        """Flip the lights."""
        return self.set_on(not self.program.on)

    @action
    def set_position(self, position: float) -> float:
        """Hold the sunset at a place, 0 (orange) to 1 (purple), until resumed."""
        return self.program.seek(_number(position, "position"))

    @action
    def nudge(self, steps: int = 1) -> float:
        """Hold the sunset a few steps darker (or, negative, brighter) than it is."""
        return self.program.seek(self.program.sunset.position + NUDGE * _number(steps, "steps"))

    @action
    def set_paused(self, paused: bool) -> bool:
        """Hold the sunset where it is, or let it run on from there."""
        if not isinstance(paused, bool):
            raise ValueError("paused must be true or false")
        self.program.set_paused(paused)
        return paused

    @action
    def toggle_paused(self) -> bool:
        """Hold the sunset if it runs, release it if it is held."""
        return self.set_paused(not self.program.sunset.paused)

    @action
    def restart(self) -> None:
        """Run the sunset from the orange end."""
        self.program.restart()

    @action
    def set_leg(self, seconds: float) -> float:
        """Change how long orange to purple takes, live and persisted."""
        return self.program.set_leg(_number(seconds, "seconds"))

    @action
    def set_peak(self, value: float) -> float:
        """Set the ceiling on brightness (0..1)."""
        return self.program.set_peak(_number(value, "value"))

    @action
    def set_dusk_level(self, value: float) -> float:
        """Set the brightness of the purple end, relative to the orange end."""
        return self.program.set_dusk_level(_number(value, "value"))

    @action
    def set_program(self, name: str) -> str:
        """Show the sunset or a dance pattern, by name."""
        if not isinstance(name, str):
            raise ValueError("name must be a program name")
        return self.program.set_program(name)

    @action
    def set_tempo(self, bpm: float) -> float:
        """Set the dance patterns' pace."""
        return self.program.set_tempo(_number(bpm, "bpm"))

    @action
    def set_spot_level(self, value: float) -> float:
        """Set the pin spots' brightness (0..1)."""
        return self.program.set_spot_level(_number(value, "value"))

    @action
    def set_spot_color(self, color: str) -> str:
        """Make the pin spots "white", or "match" them to the running program."""
        if not isinstance(color, str):
            raise ValueError("color must be white or match")
        return self.program.set_spot_color(color)

    @action
    def set_check(self, on: bool) -> bool:
        """Run the setup check (red/green/blue/white on each fixture in turn), or stop it."""
        if not isinstance(on, bool):
            raise ValueError("on must be true or false")
        if on:
            self.program.check.start()
        else:
            self.program.check.stop()
        return self.program.check.running

    @action
    def toggle_check(self) -> bool:
        """Flip the setup check."""
        return self.set_check(not self.program.check.running)

    @action
    def reset_defaults(self) -> None:
        """Every setting back to the config file's value, with the sunset showing and running."""
        self.program.reset_overrides()

    @action
    def set_debug(self, debug: bool) -> bool:
        """Show DEBUG-level lines in the log pane."""
        if debug != debug_enabled():
            logging.getLogger().setLevel(logging.DEBUG if debug else logging.INFO)
            log.info("log level %s", "DEBUG" if debug else "INFO")
        return debug

    @action
    def toggle_debug(self) -> bool:
        return self.set_debug(not debug_enabled())


def _number(value: Any, name: str) -> float:
    """A JSON number as a float; anything else is an error naming the argument."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number")
    return float(value)
