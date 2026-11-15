"""The setup check: bar by bar, colors across its columns."""

import asyncio

import pytest

from stargarden import check
from stargarden.app import Stargarden
from stargarden.config import Config, FixtureConfig, LightingConfig
from stargarden.console import Console, install_log_buffer
from stargarden.lighting.fixtures import CellState, Patch


def lit(program: Stargarden) -> dict[str, tuple[tuple[float, float, float], float]]:
    """cell name → (color, intensity) for the cells of the first fixture that are on."""
    frame = program.lighting.frame(program.lighting._clock())[0]
    return {name: (tuple(s.color), s.intensity) for name, s in frame.items() if s.intensity > 0}


@pytest.mark.asyncio
async def test_check_walks_the_bars_over_the_sunset(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "STEP_S", 0.02)
    program = Stargarden(config)
    program.lighting.fade_master(1.0, 0.0)
    console = Console(program, install_log_buffer("INFO"))
    try:
        assert console.act("set_check", {"on": True}) is True and console.status().check is True
        await asyncio.sleep(0)  # the task takes its first step
        assert program.check.bar == 0
        assert lit(program) == {"cell": ((1.0, 0.0, 0.0), check.LEVEL)}  # the test fixture is one cell, so one column: red
        program.set_on(False)
        assert lit(program) == {"cell": ((1.0, 0.0, 0.0), check.LEVEL)}  # the check shows with the lights off too
        program.lighting.fade_master(1.0, 0.0)
        assert console.act("toggle_check") is False and console.status().check is False and program.check.running is False
        await asyncio.sleep(0)
        assert lit(program)["cell"][0] != (1.0, 0.0, 0.0)  # the sunset again
    finally:
        program.check.stop()


def test_overlay_paints_one_bar_red_green_blue_white_left_to_right() -> None:
    bars = tuple(FixtureConfig(name=n, type="jolt_bar_fx2", mode="38ch", address=a) for n, a in (("a", 1), ("b", 39)))
    patch = Patch.from_config(LightingConfig(driver="console", fixtures=bars))
    bar = patch.fixtures[1]
    cols = check.columns(bar)
    assert [cols[f"rgb{i}"] for i in range(1, 9)] == [0, 1, 2, 3, 0, 1, 2, 3]  # two rows of four columns
    assert [cols[f"w{i}"] for i in range(1, 5)] == [0, 1, 2, 3]  # the white row sits among them
    overlay = check.CheckOverlay(patch)
    overlay.fixture = 1

    def frames() -> list[dict[str, CellState]]:  # the program's own look underneath: everything bright and strobing
        return [{c.name: CellState((0.5, 0.5, 0.5), 1.0, 1.0) for c in f.mode.cells} for f in patch.fixtures]

    fr = frames()
    overlay.apply(fr, patch, 0.0)
    assert all(s.intensity == 0.0 and s.strobe == 0.0 for s in fr[0].values())  # the other bar is dark, and not strobing
    red, green, blue, white = check.COLORS
    for row in (1, 5):  # both rows read red, green, blue, white left to right
        assert [fr[1][f"rgb{row + k}"].color for k in range(4)] == [red, green, blue, white]
    assert all(fr[1][f"rgb{i}"].intensity == check.LEVEL for i in range(1, 9))
    assert [fr[1][f"w{i}"].intensity for i in range(1, 5)] == [0.0, 0.0, 0.0, check.LEVEL]  # the white LED under the white column
    overlay.fixture = None
    fr = frames()
    overlay.apply(fr, patch, 0.0)
    assert all(s.intensity == 0.0 for f in fr for s in f.values())
