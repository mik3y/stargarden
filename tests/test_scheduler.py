from datetime import datetime
from zoneinfo import ZoneInfo

from stargarden.config import ScheduleConfig, SiteConfig
from stargarden.scheduler import SunSchedule

SF = SiteConfig("SF", 37.7749, -122.4194, "America/Los_Angeles")
TZ = ZoneInfo("America/Los_Angeles")


def test_night_and_day() -> None:
    s = SunSchedule(SF, ScheduleConfig(sunset_offset_min=20, sunrise_offset_min=-30))
    assert s.is_night(datetime(2026, 6, 21, 1, 0, tzinfo=TZ))
    assert not s.is_night(datetime(2026, 6, 21, 12, 0, tzinfo=TZ))
    assert not s.is_night(datetime(2026, 6, 21, 20, 30, tzinfo=TZ))  # sunset ~20:35, plus 20 min
    assert s.is_night(datetime(2026, 6, 21, 21, 10, tzinfo=TZ))
    assert s.is_night(datetime(2026, 6, 21, 5, 0, tzinfo=TZ))  # sunrise ~5:48, minus 30 min
    assert not s.is_night(datetime(2026, 6, 21, 5, 30, tzinfo=TZ))


def test_next_transition_and_disabled() -> None:
    s = SunSchedule(SF, ScheduleConfig())
    noon = datetime(2026, 6, 21, 12, 0, tzinfo=TZ)
    nxt = s.next_transition(noon)
    assert nxt is not None and nxt.date() == noon.date() and nxt.hour == 20
    late = datetime(2026, 6, 21, 23, 0, tzinfo=TZ)
    nxt = s.next_transition(late)
    assert nxt is not None and nxt.day == 22 and nxt.hour == 5
    off = SunSchedule(SF, ScheduleConfig(enabled=False))
    assert off.is_night(noon) and off.next_transition(noon) is None
