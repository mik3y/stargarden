"""The state machine at the heart of the program.

Pure logic with an injected clock: inputs are `set_night`, `set_occupied`,
`force`, and `track_finished`; `tick()` evaluates transitions and notifies
listeners. The app wraps this in an asyncio loop and translates transitions
into audio/lighting commands.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import replace
from enum import StrEnum

from .config import TimersConfig

log = logging.getLogger(__name__)

TransitionListener = Callable[["State", "State"], None]


class State(StrEnum):
    OFF = "off"
    AMBIENT = "ambient"
    PRESENCE = "presence"
    SHOW = "show"


class Conductor:
    def __init__(self, timers: TimersConfig, clock: Callable[[], float] = time.monotonic) -> None:
        self._timers = timers
        self._clock = clock
        self.state = State.OFF
        self.night = False
        self.occupied = False
        self.forced: State | None = None
        self.show_deadline: float | None = None
        self._presence_since: float | None = None  # when the current countdown started, and
        self._after_show = False  # whether it is the repeat delay (after a show) or the first
        self.shows_this_visit = 0
        self._listeners: list[TransitionListener] = []

    def add_listener(self, listener: TransitionListener) -> None:
        self._listeners.append(listener)

    # -- inputs ---------------------------------------------------------------

    def set_night(self, night: bool) -> None:
        if night != self.night:
            log.info("schedule: %s", "night" if night else "day")
        self.night = night
        self.tick()

    def set_occupied(self, occupied: bool) -> None:
        if occupied != self.occupied:
            log.info("presence: %s", "occupied" if occupied else "vacant")
        self.occupied = occupied
        self.tick()

    def force(self, state: State | None) -> None:
        log.info("manual: %s", f"force {state}" if state else "release")
        self.forced = state
        self.tick()

    @property
    def show_delays_s(self) -> tuple[float, float]:
        return self._timers.show_delay_s, self._timers.show_repeat_delay_s

    def set_show_delays(self, show_delay_s: float, show_repeat_delay_s: float) -> None:
        """Wait this long in PRESENCE before the first show, and this long after each show; a countdown
        already running is re-measured from when it started, so a shorter wait may bring the show at once."""
        if show_delay_s <= 0 or show_repeat_delay_s <= 0:
            raise ValueError(f"show delays must be positive, got {show_delay_s}, {show_repeat_delay_s}")
        self._timers = replace(self._timers, show_delay_s=show_delay_s, show_repeat_delay_s=show_repeat_delay_s)
        if self.state is State.PRESENCE and self._presence_since is not None:
            self.show_deadline = self._presence_since + (show_repeat_delay_s if self._after_show else show_delay_s)
            self.tick()

    def track_finished(self) -> None:
        if self.state is not State.SHOW:
            return
        if self.forced is State.SHOW:
            self.forced = None
        self._transition(self._natural_state(after_show=True))

    # -- evaluation -----------------------------------------------------------

    def time_to_show(self) -> float | None:
        if self.state is not State.PRESENCE or self.show_deadline is None:
            return None
        return max(0.0, self.show_deadline - self._clock())

    def tick(self) -> None:
        target = self.forced if self.forced is not None else self._natural_state()
        if target is not self.state:
            self._transition(target)

    def _natural_state(self, after_show: bool = False) -> State:
        if not self.night:
            return State.OFF
        if self.state is State.SHOW and not after_show:
            return State.SHOW  # a show runs to the end of its track
        if not self.occupied:
            return State.AMBIENT
        if self.state is State.PRESENCE and self.show_deadline is not None:
            if self._clock() >= self.show_deadline:
                return State.SHOW
        return State.PRESENCE

    def _transition(self, new: State) -> None:
        old = self.state
        self.state = new
        if new is State.PRESENCE:
            self._after_show = old is State.SHOW
            delay = self._timers.show_repeat_delay_s if self._after_show else self._timers.show_delay_s
            if not self._after_show:
                self.shows_this_visit = 0
            self._presence_since = self._clock()
            self.show_deadline = self._presence_since + delay
        else:
            self.show_deadline = self._presence_since = None
        if new is State.SHOW:
            self.shows_this_visit += 1
        log.info("state: %s -> %s", old, new)
        for listener in self._listeners:
            listener(old, new)
