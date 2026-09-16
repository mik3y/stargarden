"""Textual console: live status, virtual fixtures, layer levels, logs, and
keys to drive the program by hand (or to fake sensors in simulation)."""

import logging
from collections import deque

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, RichLog, Static

from ..app import Stargarden
from ..audio import Layer
from ..conductor import State
from ..config import SensorRole

LEVEL_STEP = 0.05
SWATCH_WIDTH = 16
LEVEL_STYLES = {"DEBUG": "dim", "INFO": "", "WARNING": "yellow", "ERROR": "bold red", "CRITICAL": "bold red"}


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
    buffer.setFormatter(logging.Formatter("%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S"))
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [buffer]
    return buffer


def _fmt_seconds(s: float | None) -> str:
    if s is None:
        return "—"
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


class StargardenApp(App):
    TITLE = "Stargarden"
    CSS = """
    #top { height: auto; }
    #status { width: 1fr; border: round $primary; padding: 0 1; }
    #right { width: 44; }
    #fixtures { border: round $secondary; padding: 0 1; height: auto; }
    #levels { border: round $secondary; padding: 0 1; height: auto; }
    #log { border: round $accent; height: 1fr; }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
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
        Binding("tab", "next_layer", "Layer", priority=True),
        Binding("left_square_bracket", "level(-1)", "Vol −", key_display="["),
        Binding("right_square_bracket", "level(1)", "Vol +", key_display="]"),
    ]

    def __init__(self, program: Stargarden, log_buffer: LogBuffer) -> None:
        super().__init__()
        self.program = program
        self.log_buffer = log_buffer
        self.selected_layer = Layer.BED

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="top"):
            yield Static(id="status")
            with Vertical(id="right"):
                yield Static(id="fixtures")
                yield Static(id="levels")
        yield RichLog(id="log", wrap=True, markup=False, highlight=False)
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(0.25, self.refresh_status)
        self.set_interval(0.1, self.refresh_fixtures)
        self.set_interval(0.25, self.drain_logs)
        self.refresh_status()
        self.refresh_fixtures()

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
            Text(f"audio  {p.audio.backend.name}, {p.config.audio.mode} @ {p.config.audio.samplerate} Hz"),
            Text(f"bed    {p.audio.current_bed.path.name if p.audio.current_bed else '—'}"),
            Text(f"music  {p.audio.current_music.title if p.audio.current_music else '—'}"),
        ]
        self.query_one("#status", Static).update(Text("\n").join(lines))
        self.refresh_levels()

    def refresh_fixtures(self) -> None:
        text = Text()
        for fixture, state in zip(self.program.patch.fixtures, self.program.lighting.last_states, strict=True):
            zones = state.zones[: fixture.profile.zones_per_row] or (state.rgb,) * 4
            glyph = "▓" if state.strobe else "█"
            for z in range(min(len(zones), SWATCH_WIDTH)):
                color = zones[z * len(zones) // min(len(zones), SWATCH_WIDTH)]
                r, g, b = (int(round(255 * min(1.0, ch * state.intensity))) for ch in color)
                text.append(glyph, style=f"rgb({r},{g},{b})")
            if fixture.profile.has_white_unit:
                w = int(round(255 * state.white))
                text.append(" ▮", style=f"rgb({w},{w},{w})")
            text.append(f" {fixture.name}\n")
        self.query_one("#fixtures", Static).update(text)

    def refresh_levels(self) -> None:
        text = Text()
        for layer in Layer:
            level = self.program.audio.level(layer)
            filled = int(round(level * 20))
            marker = "▶" if layer is self.selected_layer else " "
            text.append(f"{marker} {layer:<9} ")
            text.append("█" * filled + "░" * (20 - filled), style="green" if layer is self.selected_layer else "dim")
            text.append(f" {level:.2f}\n")
        self.query_one("#levels", Static).update(text)

    def drain_logs(self) -> None:
        log_widget = self.query_one("#log", RichLog)
        for record in self.log_buffer.drain():
            log_widget.write(Text(self.log_buffer.format(record), style=LEVEL_STYLES.get(record.levelname, "")))

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
        self.program.lighting.trigger_lightning()

    def action_discrete(self) -> None:
        self.program.audio.fire_discrete()

    def action_next_layer(self) -> None:
        layers = list(Layer)
        self.selected_layer = layers[(layers.index(self.selected_layer) + 1) % len(layers)]
        self.refresh_levels()

    def action_level(self, direction: int) -> None:
        self.program.audio.nudge_level(self.selected_layer, LEVEL_STEP * direction)
        self.refresh_levels()
