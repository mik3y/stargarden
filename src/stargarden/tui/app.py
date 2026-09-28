"""Textual console: live status, virtual fixtures, layer levels, logs, and
keys to drive the program by hand (or to fake sensors in simulation).

A view over `console.Console`: every panel renders one of its snapshots and
every key calls one of its actions, so the web console shows the same things."""

import logging
import time
from datetime import datetime

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Header, RichLog, Static

from ..audio import Layer
from ..console import LEVEL_STEP, LEVELS, Console, LogBuffer, swatch_rgb

__all__ = ["StargardenApp", "LogPane", "format_record", "swatch_rgb"]

SWATCH_WIDTH = 16
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
LOGGER_PREFIX = "stargarden."
LOGGER_WIDTH = 16
LEVEL_BADGES = {  # badge text and style per level; the message inherits the style for WARNING and up
    logging.DEBUG: ("DEBUG", "dim"),
    logging.INFO: ("INFO ", "green"),
    logging.WARNING: ("WARN ", "bold yellow"),
    logging.ERROR: ("ERROR", "bold red"),
    logging.CRITICAL: ("CRIT ", "bold white on red"),
}


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
        self._seq = 0

    def drain(self) -> None:
        records, self._seq = self._buffer.since(self._seq)
        for _, record in records:
            self.write(format_record(record))


def _fmt_seconds(s: float | None) -> str:
    if s is None:
        return "—"
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


def _fmt_clock(iso: str | None) -> str:
    return datetime.fromisoformat(iso).strftime("%H:%M") if iso else "—"


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

    def __init__(self, console: Console) -> None:
        super().__init__()
        self.control = console  # not `self.console`: that is Textual's own Rich console
        self.selected: str = Layer.BED

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            yield Static(id="status")
            with Vertical(id="right"):
                yield Static(id="fixtures")
                yield Static(id="levels")
                yield Static(self._keys_text(), id="keys")
        yield LogPane(self.control.log_buffer)

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
        s = self.control.status()
        night = "night" if s.night else "day"
        if s.night_override is not None:
            night += " (override)"
        motion = ", ".join(f"{role} {_fmt_seconds(ago)} ago" for role, ago in s.motion_ago_s.items())
        lines = [
            Text.assemble(("state  ", "bold"), (s.state.upper(), "bold cyan"), ("  [forced]" if s.forced else "", "yellow")),
            Text(f"sched  {night}; next {_fmt_clock(s.next_transition)}"),
            Text(f"space  {'occupied' if s.occupied else 'vacant'}; hold {_fmt_seconds(s.hold_remaining_s)}"),
            Text(f"motion {motion}"),
            Text(f"show   in {_fmt_seconds(s.show_in_s)}; #{s.shows_this_visit} this visit"),
            Text(""),
            Text(f"lights {s.theme} via {s.driver}, master {s.master:.2f}"),
            Text(f"storm  next strike in {_fmt_seconds(s.storm_in_s)}" + ("" if s.lightning_allowed else " (held: not in presence)")),
            Text(f"audio  {s.audio_out}, {s.audio_mode} @ {s.samplerate} Hz"),
            Text(f"bed    {s.bed or '—'}"),
            Text(f"music  {s.music or '—'}"),
        ]
        self._update("#status", Text("\n").join(lines))
        self.refresh_levels()
        self.query_one(LogPane).border_title = "log (debug)" if s.debug else "log"

    def refresh_fixtures(self) -> None:
        text = Text()
        for fixture in self.control.fixtures():
            top = fixture.rows[0] if fixture.rows else ()
            bottom = fixture.rows[-1] if len(fixture.rows) > 1 else ()  # a two-row grid (the bars) shows top and bottom in one line
            width = max(1, min(SWATCH_WIDTH // max(1, len(top)), 4))  # a single cell gets a wider swatch
            for k, cell in enumerate(top[:SWATCH_WIDTH]):
                r, g, b = cell.rgb
                if bottom:
                    r2, g2, b2 = bottom[k].rgb
                    text.append("▀" * width, style=f"rgb({r},{g},{b}) on rgb({r2},{g2},{b2})")
                else:
                    text.append(("▓" if cell.strobe else "█") * width, style=f"rgb({r},{g},{b})")
            if fixture.whites:
                text.append(" ")
                for white in fixture.whites[: SWATCH_WIDTH // 2]:
                    r, g, b = white.rgb
                    text.append("▮", style=f"rgb({r},{g},{b})")
            text.append(f" {fixture.name}\n")
        self._update("#fixtures", text)

    def refresh_levels(self) -> None:
        text = Text()
        for name in LEVELS:
            level = self.control.level(name)
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
        self.control.motion(role)

    def action_force(self, state: str) -> None:
        self.control.force(state)

    def action_release(self) -> None:
        self.control.release()

    def action_toggle_night(self) -> None:
        self.control.toggle_night()

    def action_lightning(self) -> None:
        self.control.lightning()

    def action_discrete(self) -> None:
        self.control.discrete()

    def action_toggle_debug(self) -> None:
        self.control.toggle_debug()
        self.refresh_status()

    def action_next_level(self) -> None:
        self.selected = LEVELS[(LEVELS.index(self.selected) + 1) % len(LEVELS)]
        self.refresh_levels()

    def action_level(self, direction: int) -> None:
        self.control.nudge_level(self.selected, LEVEL_STEP * direction)
        self.refresh_levels()
