"""The sunset model: there and back, held and released, and what it looks like."""

import pytest

from stargarden.sunset import BRIGHTENING, DARKENING, GLIDE_S, STOPS, Sunset, color_at, level_at


def test_runs_out_to_purple_and_back(clock) -> None:
    sunset = Sunset(leg_s=900.0, clock=clock)
    assert (sunset.position, sunset.direction, sunset.leg_remaining_s) == (0.0, DARKENING, 900.0)
    clock.advance(450)
    assert sunset.position == pytest.approx(0.5) and sunset.leg_remaining_s == pytest.approx(450)
    clock.advance(450)
    assert sunset.position == pytest.approx(1.0)
    clock.advance(225)
    assert sunset.position == pytest.approx(0.75) and sunset.direction == BRIGHTENING
    assert sunset.leg_remaining_s == pytest.approx(675)
    clock.advance(675 + 90)
    assert sunset.position == pytest.approx(0.1) and sunset.direction == DARKENING  # round again, no jump at either end


def test_seek_holds_until_resumed(clock) -> None:
    sunset = Sunset(leg_s=100.0, clock=clock)
    clock.advance(10)
    assert sunset.seek(0.8) == 0.8 and sunset.paused
    clock.advance(500)
    assert sunset.position == pytest.approx(0.8)  # stays put
    sunset.resume()
    clock.advance(10)
    assert sunset.position == pytest.approx(0.9) and sunset.direction == DARKENING  # runs on from there
    clock.advance(30)  # past the purple end and heading back
    assert sunset.position == pytest.approx(0.8) and sunset.direction == BRIGHTENING
    sunset.seek(0.5)
    sunset.resume()
    clock.advance(10)
    assert sunset.position == pytest.approx(0.4)  # a seek keeps the way it was heading
    assert sunset.seek(7) == 1.0 and sunset.seek(-1) == 0.0  # clamped
    with pytest.raises(ValueError):
        sunset.seek(float("nan"))


def test_pause_and_restart(clock) -> None:
    sunset = Sunset(leg_s=100.0, clock=clock)
    clock.advance(30)
    sunset.pause()
    clock.advance(1000)
    assert sunset.position == pytest.approx(0.3)
    sunset.resume()
    clock.advance(20)
    assert sunset.position == pytest.approx(0.5)
    sunset.pause()
    sunset.restart()
    assert sunset.position == 0.0 and not sunset.paused


def test_changing_the_length_keeps_the_place(clock) -> None:
    sunset = Sunset(leg_s=100.0, clock=clock)
    clock.advance(150)  # halfway back
    sunset.set_leg(1000.0)
    assert sunset.position == pytest.approx(0.5) and sunset.direction == BRIGHTENING
    clock.advance(100)
    assert sunset.position == pytest.approx(0.4)
    for bad in (0, 5, 1e9, float("inf")):
        with pytest.raises(ValueError):
            sunset.set_leg(bad)
    assert sunset.leg_s == 1000.0


def test_shown_glides_after_a_manual_move_and_tracks_otherwise(clock) -> None:
    sunset = Sunset(leg_s=100.0, clock=clock)
    clock.advance(20)
    assert sunset.shown() == pytest.approx(0.2)  # the running sunset is far slower than the glide
    sunset.seek(1.0)
    assert sunset.shown() == pytest.approx(0.2)
    clock.advance(GLIDE_S / 4)
    assert sunset.shown() == pytest.approx(0.45)
    clock.advance(GLIDE_S)
    assert sunset.shown() == pytest.approx(1.0)
    sunset.seek(0.0)
    sunset.snap()
    assert sunset.shown() == 0.0


def test_palette_runs_orange_to_purple_and_dims_but_never_goes_dark() -> None:
    assert color_at(0.0) == STOPS[0][1] and color_at(1.0) == STOPS[-1][1] and color_at(2.0) == STOPS[-1][1]
    r, g, b = color_at(0.0)
    assert r == 1.0 and g > 0.3 and b < 0.1  # orange
    r, g, b = color_at(0.5)
    assert r == 1.0 and g < 0.1 and b == 0.0  # red
    r, g, b = color_at(1.0)
    assert b > r > g == 0.0  # purple
    steps = [color_at(k / 200) for k in range(201)]
    assert max(max(abs(x - y) for x, y in zip(a, c, strict=True)) for a, c in zip(steps, steps[1:], strict=False)) < 0.02  # no jumps
    assert all(g2 <= g1 for (_, g1, _), (_, g2, _) in zip(steps, steps[1:], strict=False))  # green only ever drains away
    assert level_at(0.0, 0.35) == 1.0 and level_at(1.0, 0.35) == pytest.approx(0.35) and level_at(0.5, 0.35) == pytest.approx(0.675)
    sunset = Sunset(dusk_level=0.35)
    sunset.set_dusk_level(0.0)
    assert sunset.dusk_level > 0.0  # floored
    sunset.set_dusk_level(3)
    assert sunset.dusk_level == 1.0
