from stargarden.conductor import Conductor, State
from stargarden.config import TimersConfig


def make(clock) -> tuple[Conductor, list]:
    c = Conductor(TimersConfig(show_delay_s=10, show_repeat_delay_s=20), clock=clock)
    seen: list[tuple[State, State]] = []
    c.add_listener(lambda old, new: seen.append((old, new)))
    return c, seen


def test_daily_cycle(clock) -> None:
    c, seen = make(clock)
    assert c.state is State.OFF
    c.set_night(True)
    assert c.state is State.AMBIENT
    c.set_night(False)
    assert c.state is State.OFF
    assert seen == [(State.OFF, State.AMBIENT), (State.AMBIENT, State.OFF)]


def test_visit_with_shows(clock) -> None:
    c, _ = make(clock)
    c.set_night(True)
    c.set_occupied(True)
    assert c.state is State.PRESENCE
    assert c.time_to_show() == 10
    clock.advance(9)
    c.tick()
    assert c.state is State.PRESENCE
    clock.advance(1)
    c.tick()
    assert c.state is State.SHOW
    assert c.shows_this_visit == 1

    # a show runs to the end of its track even if the space empties
    c.set_occupied(False)
    assert c.state is State.SHOW
    c.set_occupied(True)
    c.track_finished()
    assert c.state is State.PRESENCE
    assert c.time_to_show() == 20  # repeat delay
    assert c.shows_this_visit == 1

    clock.advance(20)
    c.tick()
    assert c.state is State.SHOW
    c.track_finished()
    assert c.shows_this_visit == 2
    c.set_occupied(False)
    assert c.state is State.AMBIENT
    c.set_occupied(True)
    assert c.shows_this_visit == 0


def test_vacated_during_show_returns_to_ambient(clock) -> None:
    c, _ = make(clock)
    c.set_night(True)
    c.set_occupied(True)
    clock.advance(10)
    c.tick()
    assert c.state is State.SHOW
    c.set_occupied(False)
    c.track_finished()
    assert c.state is State.AMBIENT


def test_day_interrupts_show(clock) -> None:
    c, _ = make(clock)
    c.set_night(True)
    c.set_occupied(True)
    clock.advance(10)
    c.tick()
    assert c.state is State.SHOW
    c.set_night(False)
    assert c.state is State.OFF
    c.track_finished()  # ignored: not in a show
    assert c.state is State.OFF


def test_force_and_release(clock) -> None:
    c, _ = make(clock)
    c.force(State.SHOW)
    assert c.state is State.SHOW
    c.set_night(False)
    assert c.state is State.SHOW
    c.track_finished()  # forced show ends: force released, natural state resumes
    assert c.forced is None
    assert c.state is State.OFF

    c.force(State.AMBIENT)
    c.set_occupied(True)
    assert c.state is State.AMBIENT
    c.force(None)
    assert c.state is State.OFF  # still day
    c.set_night(True)
    assert c.state is State.PRESENCE
