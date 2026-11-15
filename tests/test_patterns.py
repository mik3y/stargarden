"""The dance patterns: bounded, eased, and blocky in the ways they claim."""

import pytest

from stargarden.lighting.engine import Spot
from stargarden.patterns import PALETTE, PATTERNS, Blocks, Chase, Checker, Pulse

BARS, COLS, ROWS = 4, 4, 2  # four Jolt bars in 38CH
SPOTS = [Spot(bar, BARS, col, COLS, row, ROWS) for bar in range(BARS) for row in range(ROWS) for col in range(COLS)]
STEPS_PER_BEAT = 18  # 30 fps at 100 bpm


def lit(pattern, spot: Spot, beat: float) -> tuple[float, float, float]:
    """A cell's light, color times brightness."""
    color, level = pattern.cell(spot, beat)
    return tuple(c * level for c in color)


@pytest.mark.parametrize("name", list(PATTERNS))
def test_patterns_are_bounded_eased_and_never_dark(name: str) -> None:
    pattern = PATTERNS[name]
    assert pattern.name == name
    worst = 0.0
    for k in range(64 * STEPS_PER_BEAT):  # four phrases
        beat = k / STEPS_PER_BEAT
        assert all(0.0 <= c <= 1.0 for c in pattern.accent(beat))
        total = 0.0
        for spot in SPOTS:
            color, level = pattern.cell(spot, beat)
            assert 0.0 < level <= 1.0 and all(0.0 <= c <= 1.0 for c in color)
            total += level
            after = lit(pattern, spot, beat + 1 / STEPS_PER_BEAT)
            worst = max(worst, max(abs(a - b) for a, b in zip(lit(pattern, spot, beat), after, strict=True)))
        assert total > 2.0  # the room never goes dark
    assert worst < 0.45  # no cuts or flashes: the fastest move still takes a few frames


def test_blocks_hold_half_bars_and_take_turns() -> None:
    pattern = Blocks()
    for beat in (3.0, 11.5, 40.25):
        for bar in range(BARS):
            cells = {(col, row): pattern.cell(Spot(bar, BARS, col, COLS, row, ROWS), beat) for col in range(COLS) for row in range(ROWS)}
            assert cells[0, 0] == cells[1, 0] == cells[0, 1] == cells[1, 1]  # the left half is one block
            assert cells[2, 0] == cells[3, 0] == cells[2, 1] == cells[3, 1]
    first = Spot(0, BARS, 0, COLS)
    assert pattern.cell(first, 1.5) == pattern.cell(first, 7.9)  # held between changes
    assert pattern.cell(first, 1.5)[0] != pattern.cell(first, 9.5)[0]  # a new color each hold
    changing = [
        b
        for b in range(8)
        if pattern.cell(Spot(b // 2, BARS, (b % 2) * 2, COLS), 16.5) != pattern.cell(Spot(b // 2, BARS, (b % 2) * 2, COLS), 17.5)
    ]
    assert changing == [0, 4]  # a pair on different bars moves at a time
    assert all(pattern.cell(spot, 5.0)[0] in PALETTE for spot in SPOTS)


def test_chase_runs_two_heads_half_the_room_apart() -> None:
    pattern = Chase()
    for beat in (5.0, 6.0, 21.0):
        levels = [pattern.cell(Spot(c // COLS, BARS, c % COLS, COLS), beat)[1] for c in range(BARS * COLS)]
        heads = sorted(c for c, level in enumerate(levels) if level == 1.0)
        assert heads == sorted({(int(beat) - 1) % 16, (int(beat) - 1 + 8) % 16})  # one column per beat
        assert levels[(heads[0] - 2) % 16] < levels[(heads[0] - 1) % 16] < 1.0  # a tail behind
        assert levels[(heads[0] + 2) % 16] == pattern.floor_level  # dark ahead
    top, bottom = Spot(1, BARS, 2, COLS, 0, ROWS), Spot(1, BARS, 2, COLS, 1, ROWS)
    assert pattern.cell(top, 7.3) == pattern.cell(bottom, 7.3)  # both rows of a column move together


def test_checker_trades_places() -> None:
    pattern = Checker()
    a, b, under = Spot(0, BARS, 0, COLS, 0, ROWS), Spot(0, BARS, 1, COLS, 0, ROWS), Spot(0, BARS, 0, COLS, 1, ROWS)
    assert pattern.cell(a, 5.0) == pattern.cell(Spot(0, BARS, 2, COLS, 0, ROWS), 5.0) == pattern.cell(Spot(0, BARS, 1, COLS, 1, ROWS), 5.0)
    assert pattern.cell(a, 5.0) != pattern.cell(b, 5.0) and pattern.cell(b, 5.0) == pattern.cell(under, 5.0)
    assert pattern.cell(a, 5.0) == pattern.cell(b, 7.0) and pattern.cell(b, 5.0) == pattern.cell(a, 7.0)  # swapped two beats on
    assert {pattern.cell(a, 5.0)[1], pattern.cell(b, 5.0)[1]} == {1.0, pattern.back_level}


def test_pulse_gives_each_bar_its_beat() -> None:
    pattern = Pulse()
    for bar in range(BARS):
        middle = [pattern.cell(Spot(k, BARS, 1, COLS), bar + 0.3)[1] for k in range(BARS)]
        assert middle.index(max(middle)) == bar and max(middle) > 0.9
        assert middle[(bar + 1) % BARS] < 0.2  # the bar longest since its beat has sunk to the floor
    inner, outer = pattern.cell(Spot(0, BARS, 1, COLS), 0.15)[1], pattern.cell(Spot(0, BARS, 0, COLS), 0.15)[1]
    assert inner > outer  # the swell starts in the middle of the bar
    assert pattern.cell(Spot(0, BARS, 1, COLS), 0.2) == pattern.cell(Spot(0, BARS, 2, COLS), 0.2)  # and is symmetrical
