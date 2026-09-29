"""The setup check: corner by corner, a tone on that speaker and colors on that bar."""

import asyncio

import numpy as np
import pytest

from stargarden import check
from stargarden.app import Stargarden
from stargarden.audio import Layer
from stargarden.conductor import State
from stargarden.config import FixtureConfig, LightingConfig
from stargarden.console import Console, install_log_buffer
from stargarden.lighting.fixtures import CellKind, CellState, Patch
from stargarden.manifest import load_manifest
from test_app import make_config


def lit(program: Stargarden) -> dict[str, tuple[tuple[float, float, float], float]]:
    """cell name → (color, intensity) for the cells of the first fixture that are on."""
    frame = program.lighting.frame(program.lighting._clock())[0]
    return {name: (tuple(s.color), s.intensity) for name, s in frame.items() if s.intensity > 0}


@pytest.mark.asyncio
async def test_check_walks_colors_and_corners(tmp_path, assets, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check, "STEP_S", 0.02)
    config = make_config(tmp_path, assets)
    program = Stargarden(config, load_manifest(config.assets_root), seed=1)
    program.conductor.set_night(True)
    program.conductor.force(State.PRESENCE)
    console = Console(program, install_log_buffer("INFO"))
    program.audio.start()
    try:
        assert console.act("set_check", {"on": True}) is True and console.status().check is True
        assert program.conductor.forced is State.OFF  # pinned off while the check runs
        await asyncio.sleep(0)  # the task takes its first step
        assert program.check.corner == 0
        cells = {c.name for c in program.patch.fixtures[0].mode.cells}  # the test fixture: one RGBW cell, no white cells
        # red first, dim
        on = lit(program)
        assert set(on) == cells and all(on[n] == ((1.0, 0.0, 0.0), check.LEVEL) for n in cells)
        # a tone on output 1, mono, on the first output only
        voice = next(v for v in program.audio.mixer.voices(Layer.DISCRETES) if v.name == "check:1")
        block = voice.render(64)
        assert block.shape == (64, 4) and np.any(block[:, 0] != 0) and not np.any(block[:, 1:] != 0)
        # ... then green, blue, white
        colors = []
        for _ in range(3):
            await asyncio.sleep(0.02)
            colors.append(next(iter(lit(program).values()))[0])
        assert colors == [(0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (1.0, 1.0, 1.0)]
        # corner 2: the only fixture is dark, the tone is on output 2
        await asyncio.sleep(0.02)
        assert program.check.corner == 1 and lit(program) == {}
        voice = next(v for v in program.audio.mixer.voices(Layer.DISCRETES) if v.name == "check:2")
        block = voice.render(64)
        assert np.any(block[:, 1] != 0) and not np.any(block[:, [0, 2, 3]] != 0)
        # off: the state comes back and the lights are the program's again
        assert console.act("toggle_check") is False and console.status().check is False
        assert program.conductor.forced is State.PRESENCE and program.check.running is False
        await asyncio.sleep(0)
        assert lit(program) != {} and all(c != (1.0, 0.0, 0.0) for c, _ in lit(program).values())
    finally:
        program.check.stop()
        program.audio.stop()


def test_overlay_lights_one_bar_and_its_whites_on_the_white_step() -> None:
    bars = tuple(FixtureConfig(name=n, type="jolt_bar_fx2", mode="38ch", address=a) for n, a in (("a", 1), ("b", 39)))
    cfg = LightingConfig(driver="console", fixtures=bars)
    patch = Patch.from_config(cfg)
    whites = {c.name for c in patch.fixtures[0].mode.cells if c.kind is CellKind.WHITE}
    colors = {c.name for c in patch.fixtures[0].mode.cells if c.kind is CellKind.COLOR}
    assert whites and colors
    overlay = check.CheckOverlay()
    overlay.fixture, overlay.color, overlay.white = 1, (0.0, 0.0, 1.0), False

    def frames() -> list[dict[str, CellState]]:  # the program's own look underneath: everything bright and strobing
        return [{c.name: CellState((0.5, 0.5, 0.5), 1.0, 1.0) for c in f.mode.cells} for f in patch.fixtures]

    fr = frames()
    overlay.apply(fr, patch, 0.0)
    assert all(s.intensity == 0.0 and s.strobe == 0.0 for s in fr[0].values())  # the other bar is dark, and not strobing
    assert {n for n, s in fr[1].items() if s.intensity > 0} == colors
    assert all(fr[1][n].color == (0.0, 0.0, 1.0) and fr[1][n].intensity == check.LEVEL for n in colors)
    overlay.color, overlay.white = (1.0, 1.0, 1.0), True
    fr = frames()
    overlay.apply(fr, patch, 0.0)
    assert {n for n, s in fr[1].items() if s.intensity > 0} == colors | whites  # the white step lights the white LEDs too
    assert all(fr[1][n].intensity == check.LEVEL for n in whites)
    overlay.fixture = None  # a corner with a speaker but no bar
    fr = frames()
    overlay.apply(fr, patch, 0.0)
    assert all(s.intensity == 0.0 for f in fr for s in f.values())


def test_tone_is_soft_and_ramped() -> None:
    clip = check.tone(48_000, 440.0, 0.5, 0.25)
    assert clip.shape == (24_000, 1) and clip.dtype == np.float32
    assert np.abs(clip).max() == pytest.approx(0.25, abs=0.01)
    assert np.abs(clip[:10]).max() < 0.01 and np.abs(clip[-10:]).max() < 0.01
