"""Sunset/sunrise schedule: decides whether it is "night" (installation on)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from astral import LocationInfo
from astral.sun import sun

from .config import ScheduleConfig, SiteConfig


class SunSchedule:
    def __init__(self, site: SiteConfig, schedule: ScheduleConfig) -> None:
        self._schedule = schedule
        self._tz = ZoneInfo(site.timezone)
        self._observer = LocationInfo(site.name, "", site.timezone, site.latitude, site.longitude).observer

    @property
    def tz(self) -> ZoneInfo:
        return self._tz

    def now(self) -> datetime:
        return datetime.now(self._tz)

    def bounds(self, day: datetime) -> tuple[datetime, datetime]:
        """(lights-off, lights-on) instants for the calendar day containing `day`."""
        s = sun(self._observer, date=day.date(), tzinfo=self._tz)
        off = s["sunrise"] + timedelta(minutes=self._schedule.sunrise_offset_min)
        on = s["sunset"] + timedelta(minutes=self._schedule.sunset_offset_min)
        return off, on

    def is_night(self, now: datetime | None = None) -> bool:
        if not self._schedule.enabled:
            return True
        now = now or self.now()
        off, on = self.bounds(now)
        return now < off or now >= on

    def next_transition(self, now: datetime | None = None) -> datetime | None:
        if not self._schedule.enabled:
            return None
        now = now or self.now()
        off, on = self.bounds(now)
        if now < off:
            return off
        if now < on:
            return on
        return self.bounds(now + timedelta(days=1))[0]
