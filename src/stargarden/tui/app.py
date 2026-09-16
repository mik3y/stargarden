"""Textual console: live status, virtual fixtures, layer levels, logs, and
keys to drive the program by hand (or to fake sensors in simulation)."""

import logging
import time
from collections import deque

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Header, RichLog, Static

from ..app import Stargarden
from ..audio import Layer
from ..conductor import State
from ..config import SensorRole

LEVEL_STEP = 0.05
PEAK = "peak"  # the lighting ceiling, mixed in with the audio layers in the levels panel
LEVELS: tuple[str, ...] = (*Layer, PEAK)
SWATCH_WIDTH = 16
LOGGER_PREFIX = "stargarden."
KEYS = (
    ("m / w", "platform / walkway motion"),
    ("0 1 2 3", "force off/ambient/presence/show"),
    ("r", "release forced state"),
    ("n", "toggle day / night"),
    ("l / s", "lightning / discrete sound"),
    ("d", "debug logging"),
    ("tab [ ]", "select level, nudge −/+"),
    ("q", "quit"),
)
LOGGER_WIDTH = 16
LEVEL_BADGES = {  # badge text and style per level; the message inherits the style for WARNING and up
    logging.DEBUG: ("DEBUG", "dim"),
    logging.INFO: ("INFO ", "green"),
    logging.WARNING: ("WARN ", "bold yellow"),
    logging.ERROR: ("ERROR", "bold red"),
    logging.CRITICAL: ("CRIT ", "bold white on red"),
}


class LogBuffer(logging.Handler):
    """Thread-safe holding pen for log records; the console drains it on a timer."""

    def __init__(self, maxlen: int = 500) -> None:
        super().__init__()
        self.records: deque[logging.LogRecord] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def drain(self) -> list[logging.LogRecord]:
        out = []
        while self.records:
            out.append(self.records.popleft())
        return out


def install_log_buffer(level: str) -> LogBuffer:
    buffer = LogBuffer()
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [buffer]
    return buffer


def format_record(record: logging.LogRecord) -> Text:
    """One log line as aligned columns: time, level badge, logger, message (+ traceback)."""
    badge, style = LEVEL_BADGES.get(record.levelno, (record.levelname[:5].ljust(5), ""))
    name = record.name.removeprefix(LOGGER_PREFIX)
    if len(name) > LOGGER_WIDTH:
        name = "…" + name[-(LOGGER_WIDTH - 1) :]
    line = Text()
    line.append(time.strftime("%H:%M:%S", time.localtime(record.created)) + f".{int(record.msecs):03d} ", style="dim")
    line.append(badge, style=style)
    line.append(f" {name:<{LOGGER_WIDTH}} ", style="cyan")
    line.append(record.getMessage(), style=style if record.levelno >= logging.WARNING else "")
    if record.exc_info:
        line.append("\n" + logging.Formatter().formatException(record.exc_info), style="red")
    return line


class LogPane(RichLog):
    """The log stream, newest at the bottom; scrolls with the output unless you scroll up."""

    BORDER_TITLE = "log"

    def __init__(self, buffer: LogBuffer) -> None:
        super().__init__(id="log", wrap=True, markup=False, highlight=False)
        self._buffer = buffer

    def drain(self) -> None:
        for record in self._buffer.drain():
            self.write(format_record(record))


def swatch_rgb(color: tuple[float, float, float], intensity: float, peak: float) -> tuple[int, int, int]:
    """Terminal color for a cell, previewed as if the peak were 1.0: a softened rig
    still shows its look in the console rather than a row of black squares."""
    level = min(1.0, intensity / peak if peak > 0 else intensity)  # an overlay's absolute level must not overshoot
    return tuple(int(round(255 * min(1.0, ch * level))) for ch in color)


def _fmt_seconds(s: float | None) -> str:
    if s is None:
        return "—"
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


class StargardenApp(App):
    TITLE = "Stargarden"
    CSS = """
    #top { height: auto; }
    #status { width: 1fr; height: auto; border: round $primary; padding: 0 1; }
    #right { width: 46; height: auto; }
    #fixtures, #levels, #keys { height: auto; border: round $secondary; padding: 0 1; }
    #log { height: 1fr; border: round $accent; padding: 0 1; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),  # Textual's default only hints at ctrl+q
        Binding("m", "motion('platform')", "Platform motion"),
        Binding("w", "motion('walkway')", "Walkway motion"),
        Binding("0", "force('off')", "Force OFF"),
        Binding("1", "force('ambient')", "Force AMBIENT"),
        Binding("2", "force('presence')", "Force PRESENCE"),
        Binding("3", "force('show')", "Force SHOW"),
        Binding("r", "release", "Release"),
        Binding("n", "toggle_night", "Day/night"),
        Binding("l", "lightning", "Lightning"),
        Binding("s", "discrete", "Sound"),
        Binding("d", "toggle_debug", "Debug log"),
        Binding("tab", "next_level", "Level", priority=True),
        Binding("left_square_bracket", "level(-1)", "Level −", key_display="["),
        Binding("right_square_bracket", "level(1)", "Level +", key_display="]"),
    ]

    def __init__(self, program: Stargarden, log_buffer: LogBuffer) -> None:
        super().__init__()
        self.program = program
        self.log_buffer = log_buffer
        self.selected: str = Layer.BED

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            yield Static(id="status")
            with Vertical(id="right"):
                yield Static(id="fixtures")
                yield Static(id="levels")
                yield Static(self._keys_text(), id="keys")
        yield LogPane(self.log_buffer)

    @staticmethod
    def _keys_text() -> Text:
        text = Text()
        for key, action in KEYS:
            text.append(f"{key:<8}", style="bold")
            text.append(f"{action}\n", style="dim")
        text.rstrip()
        return text

    def on_mount(self) -> None:
        for widget_id in ("status", "fixtures", "levels", "keys"):
            self.query_one(f"#{widget_id}", Static).border_title = widget_id
        self._refresh_timers = [  # not `_timers`: that is Textual's own set of timers
            self.set_interval(0.25, self.refresh_status),
            self.set_interval(0.1, self.refresh_fixtures),
            self.set_interval(0.25, self.query_one(LogPane).drain),
        ]
        self.refresh_status()
        self.refresh_fixtures()

    def on_unmount(self) -> None:
        for timer in self._refresh_timers:  # don't let a refresh land on widgets that are already gone
            timer.stop()

    # -- panels ---------------------------------------------------------------

    def refresh_status(self) -> None:
        p = self.program
        c = p.conductor
        night = "night" if c.night else "day"
        if p.night_override is not None:
            night += " (override)"
        nxt = p.schedule.next_transition()
        platform_ago = _fmt_seconds(p.occupancy.seconds_since(SensorRole.PLATFORM))
        walkway_ago = _fmt_seconds(p.occupancy.seconds_since(SensorRole.WALKWAY))
        lines = [
            Text.assemble(("state  ", "bold"), (c.state.upper(), "bold cyan"), ("  [forced]" if c.forced else "", "yellow")),
            Text(f"sched  {night}; next {nxt.strftime('%H:%M') if nxt else '—'}"),
            Text(f"space  {'occupied' if p.occupancy.occupied else 'vacant'}; hold {_fmt_seconds(p.occupancy.hold_remaining())}"),
            Text(f"motion platform {platform_ago} ago, walkway {walkway_ago} ago"),
            Text(f"show   in {_fmt_seconds(c.time_to_show())}; #{c.shows_this_visit} this visit"),
            Text(""),
            Text(f"lights {p.lighting.theme.name} via {p.lighting.driver.name}, master {p.lighting.master():.2f}"),
            Text(
                f"storm  next strike in {_fmt_seconds(p.lightning.time_to_next())}"
                + ("" if p.lightning_allowed() else " (held: not in presence)")
            ),
            Text(f"audio  {p.audio.backend.name}, {p.config.audio.mode} @ {p.config.audio.samplerate} Hz"),
            Text(f"bed    {p.audio.current_bed.path.name if p.audio.current_bed else '—'}"),
            Text(f"music  {p.audio.current_music.title if p.audio.current_music else '—'}"),
        ]
        self._update("#status", Text("\n").join(lines))
        self.refresh_levels()

    def refresh_fixtures(self) -> None:
        text = Text()
        peak = self.program.lighting.peak
        for fixture, frame in zip(self.program.patch.fixtures, self.program.lighting.last_frames, strict=True):
            mode = fixture.mode
            ys = sorted({c.position[1] for c in mode.color_cells})
            rows = [sorted((c for c in mode.color_cells if c.position[1] == y), key=lambda c: c.position[0]) for y in ys]
            top = rows[0] if rows else []
            bottom = rows[-1] if len(rows) > 1 else []  # a two-row grid (the bars) shows top and bottom in one line
            width = max(1, min(SWATCH_WIDTH // max(1, len(top)), 4))  # a single cell gets a wider swatch
            for k, cell in enumerate(top[:SWATCH_WIDTH]):
                state = frame[cell.name]
                r, g, b = swatch_rgb(state.color, state.intensity, peak)
                if bottom:
                    r2, g2, b2 = swatch_rgb(frame[bottom[k].name].color, frame[bottom[k].name].intensity, peak)
                    text.append("▀" * width, style=f"rgb({r},{g},{b}) on rgb({r2},{g2},{b2})")
                else:
                    text.append(("▓" if state.strobe else "█") * width, style=f"rgb({r},{g},{b})")
            if mode.white_cells:
                text.append(" ")
                for cell in mode.white_cells[: SWATCH_WIDTH // 2]:
                    w = int(round(255 * frame[cell.name].intensity))
                    text.append("▮", style=f"rgb({w},{w},{w})")
            text.append(f" {fixture.name}\n")
        self._update("#fixtures", text)

    def refresh_levels(self) -> None:
        text = Text()
        for name in LEVELS:
            level = self.program.lighting.peak if name == PEAK else self.program.audio.level(Layer(name))
            filled = int(round(level * 20))
            selected = name == self.selected
            text.append(f"{'▶' if selected else ' '} {name:<9} ")
            text.append("█" * filled + "░" * (20 - filled), style="green" if selected else "dim")
            text.append(f" {level:.2f}\n")
        self._update("#levels", text)

    def _update(self, selector: str, content: Text) -> None:
        try:
            self.query_one(selector, Static).update(content)
        except NoMatches:
            pass  # a refresh timer fired while the screen was being torn down

    # -- actions --------------------------------------------------------------

    def action_motion(self, role: str) -> None:
        self.program.simulate_motion(SensorRole(role))

    def action_force(self, state: str) -> None:
        self.program.conductor.force(State(state))

    def action_release(self) -> None:
        self.program.conductor.force(None)

    def action_toggle_night(self) -> None:
        self.program.set_night_override(not self.program.conductor.night)

    def action_lightning(self) -> None:
        self.program.lightning.strike()

    def action_discrete(self) -> None:
        self.program.audio.fire_discrete()

    def action_toggle_debug(self) -> None:
        root = logging.getLogger()
        debug = root.level > logging.DEBUG
        root.setLevel(logging.DEBUG if debug else logging.INFO)
        logging.getLogger(__name__).info("log level %s", "DEBUG" if debug else "INFO")
        self.query_one(LogPane).border_title = "log (debug)" if debug else "log"

    def action_next_level(self) -> None:
        self.selected = LEVELS[(LEVELS.index(self.selected) + 1) % len(LEVELS)]
        self.refresh_levels()

    def action_level(self, direction: int) -> None:
        if self.selected == PEAK:
            self.program.lighting.nudge_peak(LEVEL_STEP * direction)
        else:
            self.program.audio.nudge_level(Layer(self.selected), LEVEL_STEP * direction)
        self.refresh_levels()
