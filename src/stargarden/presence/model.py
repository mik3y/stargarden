"""Latching occupancy model over raw motion events.

Platform motion means someone is definitely there; the space is then held
occupied until no sensor has reported motion for `vacancy_timeout_s`, since a
still, stargazing visitor won't keep retriggering a PIR. Walkway motion alone
never starts occupancy (it can't tell arrivals from passers-by) but it does
refresh the hold and is recorded as a likely approach.
"""

import logging
import time
from collections.abc import Callable

from ..config import SensorRole

log = logging.getLogger(__name__)


class OccupancyModel:
    def __init__(self, vacancy_timeout_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.vacancy_timeout_s = vacancy_timeout_s
        self._clock = clock
        self.last_motion: dict[SensorRole, float] = {}
        self.occupied_since: float | None = None
        self.hold_until: float | None = None
        self.last_approach: float | None = None

    def motion(self, role: SensorRole) -> None:
        now = self._clock()
        self.last_motion[role] = now
        if self.occupied:
            self.hold_until = now + self.vacancy_timeout_s
        elif role is SensorRole.PLATFORM:
            log.info("presence: platform motion, space occupied")
            self.occupied_since = now
            self.hold_until = now + self.vacancy_timeout_s
        else:
            self.last_approach = now
            log.debug("presence: walkway motion (approach?)")

    @property
    def occupied(self) -> bool:
        if self.hold_until is None:
            return False
        if self._clock() < self.hold_until:
            return True
        self.hold_until = None
        self.occupied_since = None
        return False

    def hold_remaining(self) -> float | None:
        if not self.occupied or self.hold_until is None:
            return None
        return self.hold_until - self._clock()

    def seconds_since(self, role: SensorRole) -> float | None:
        t = self.last_motion.get(role)
        return None if t is None else self._clock() - t
