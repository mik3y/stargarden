"""The control surface shared by every console.

What a console shows (a `Status` snapshot, the fixture preview, the log stream)
and what it may do (the `Console` actions) live here, so the Textual TUI and the
web console are thin views over one model and cannot drift apart. A new control
is added here first — a field on `Status`, or an `@action` method on `Console` —
and each front end then shows it its own way (`tui/app.py`, `web.py` and `web/`).
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .app import Stargarden
from .audio import Layer
from .conductor import State
from .config import SensorRole
from .lighting.color import RGB

log = logging.getLogger(__name__)

LEVEL_STEP = 0.05
PEAK = "peak"  # the lighting ceiling, shown alongside the audio layers
LEVELS: tuple[str, ...] = (*Layer, PEAK)
LOGGER_PREFIX = "stargarden."
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class ActionError(Exception):
    """A console action was called with arguments it cannot use."""


class UnknownAction(ActionError):
    pass


# -- log stream -----------------------------------------------------------------


class LogBuffer(logging.Handler):
    """Ring of recent log records, numbered so that several consoles can each read
    from where they left off. Records arrive from any thread (the audio callback
    logs too); `since` is safe to call from the event loop."""

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


def install_log_buffer(level: str, stderr: bool = False) -> LogBuffer:
    """Route the root logger into a `LogBuffer` (and, headless, to stderr as well)."""
    buffer = LogBuffer()
    handlers: list[logging.Handler] = [buffer]
    if stderr:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(LOG_FORMAT))
        handlers.append(stream)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = handlers
    logging.captureWarnings(True)  # Python warnings reach the consoles instead of the terminal
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


# -- snapshots ------------------------------------------------------------------


@dataclass(frozen=True)
class Status:
    """Everything a console's status panel shows, as plain data (JSON-ready)."""

    site: str
    state: str
    forced: str | None
    night: bool
    night_override: bool | None
    next_transition: str | None  # ISO 8601 in the site's timezone, or None when the schedule is off
    occupied: bool
    hold_remaining_s: float | None
    motion_ago_s: dict[str, float | None]  # by sensor role
    show_in_s: float | None
    shows_this_visit: int
    theme: str
    driver: str
    master: float
    storm_in_s: float | None
    lightning_allowed: bool
    audio_out: str
    audio_mode: str
    samplerate: int
    bed: str | None
    music: str | None
    levels: dict[str, float]  # audio layers and the lighting peak, in LEVELS order
    debug: bool


@dataclass(frozen=True)
class CellPreview:
    name: str  # the cell's name in its fixture mode
    rgb: tuple[int, int, int]
    strobe: bool = False


@dataclass(frozen=True)
class FixturePreview:
    """A fixture's color cells row by row (top first, left to right), and its white
    cells (what lightning flashes) as grey swatches."""

    name: str
    rows: tuple[tuple[CellPreview, ...], ...]
    whites: tuple[CellPreview, ...]


def swatch_rgb(color: RGB, intensity: float, peak: float) -> tuple[int, int, int]:
    """Preview color for a cell, as if the peak were 1.0: a softened rig still shows
    its look in the console rather than a row of black squares."""
    level = min(1.0, intensity / peak if peak > 0 else intensity)  # an overlay's absolute level must not overshoot
    r, g, b = (int(round(255 * min(1.0, ch * level))) for ch in color)
    return r, g, b


def _fmt_dt(dt) -> str | None:
    return dt.isoformat(timespec="seconds") if dt is not None else None


# -- the console ----------------------------------------------------------------


def action(fn: Callable) -> Callable:
    """Mark a `Console` method as callable by name (`Console.act`), e.g. from the web API."""
    fn.__console_action__ = True  # type: ignore[attr-defined]
    return fn


class Console:
    """Snapshots of the program for display, and the actions a console may take on it."""

    def __init__(self, program: Stargarden, log_buffer: LogBuffer) -> None:
        self.program = program
        self.log_buffer = log_buffer

    # -- snapshots ----------------------------------------------------------------

    def status(self) -> Status:
        p = self.program
        c = p.conductor
        return Status(
            site=p.config.site.name,
            state=c.state.value,
            forced=c.forced.value if c.forced else None,
            night=c.night,
            night_override=p.night_override,
            next_transition=_fmt_dt(p.schedule.next_transition()),
            occupied=p.occupancy.occupied,
            hold_remaining_s=p.occupancy.hold_remaining(),
            motion_ago_s={role.value: p.occupancy.seconds_since(role) for role in SensorRole},
            show_in_s=c.time_to_show(),
            shows_this_visit=c.shows_this_visit,
            theme=p.lighting.theme.name,
            driver=p.lighting.driver.name,
            master=p.lighting.master(),
            storm_in_s=p.lightning.time_to_next(),
            lightning_allowed=p.lightning_allowed(),
            audio_out=getattr(p.audio.backend, "device_name", p.audio.backend.name),
            audio_mode=p.config.audio.mode.value,
            samplerate=p.config.audio.samplerate,
            bed=p.audio.current_bed.path.name if p.audio.current_bed else None,
            music=p.audio.current_music.title if p.audio.current_music else None,
            levels={name: self.level(name) for name in LEVELS},
            debug=debug_enabled(),
        )

    def fixtures(self) -> list[FixturePreview]:
        p = self.program
        peak = p.lighting.peak
        previews = []
        for fixture, frame in zip(p.patch.fixtures, p.lighting.last_frames, strict=True):
            mode = fixture.mode
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

    def level(self, name: str) -> float:
        if name == PEAK:
            return self.program.lighting.peak
        return self.program.audio.level(Layer(name))

    # -- actions ------------------------------------------------------------------

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
    def motion(self, role: str) -> None:
        """Fake a motion event from the platform or walkway sensor."""
        self.program.simulate_motion(SensorRole(role))

    @action
    def force(self, state: str | None) -> None:
        """Pin the program to a state until released (`state = None`)."""
        self.program.conductor.force(State(state) if state is not None else None)

    @action
    def release(self) -> None:
        self.program.conductor.force(None)

    @action
    def set_night(self, night: bool | None) -> None:
        """Override the sunset schedule (True = night, False = day); None hands it back to the schedule."""
        if night is not None and not isinstance(night, bool):
            raise ValueError("night must be true, false or null")
        self.program.set_night_override(night)

    @action
    def toggle_night(self) -> bool:
        night = not self.program.conductor.night
        self.program.set_night_override(night)
        return night

    @action
    def lightning(self) -> None:
        self.program.lightning.strike()

    @action
    def discrete(self) -> bool:
        return self.program.audio.fire_discrete()

    @action
    def set_level(self, name: str, value: float) -> float:
        """Set an audio layer's level or the lighting peak (0..1)."""
        if name not in LEVELS:
            raise ValueError(f"unknown level {name!r}; have {list(LEVELS)}")
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("value must be a number")
        value = min(1.0, max(0.0, float(value)))
        if name == PEAK:
            self.program.lighting.set_peak(value)
        else:
            self.program.audio.set_level(Layer(name), value)
        return self.level(name)

    @action
    def nudge_level(self, name: str, delta: float) -> float:
        return self.set_level(name, self.level(name) + delta)

    @action
    def set_debug(self, debug: bool) -> bool:
        """Show DEBUG-level lines in the consoles' log panes."""
        if debug != debug_enabled():
            logging.getLogger().setLevel(logging.DEBUG if debug else logging.INFO)
            log.info("log level %s", "DEBUG" if debug else "INFO")
        return debug

    @action
    def toggle_debug(self) -> bool:
        return self.set_debug(not debug_enabled())
