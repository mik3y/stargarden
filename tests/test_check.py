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
from stargarden.lighting.fixtures import CellState, Patch
from stargarden.manifest import load_manifest
from test_app import make_config
from test_audio import fake_sd  # noqa: F401


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
        cells = {c.name for c in program.patch.fixtures[0].mode.cells}  # the test fixture: one RGBW cell, so one column: red
        on = lit(program)
        assert set(on) == cells and all(on[n] == ((1.0, 0.0, 0.0), check.LEVEL) for n in cells)
        # a tone on output 1, mono, on the first output only
        voice = next(v for v in program.audio.mixer.voices(Layer.DISCRETES) if v.name == "check:1")
        block = voice.render(64)
        assert block.shape == (64, 4) and np.any(block[:, 0] != 0) and not np.any(block[:, 1:] != 0)
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
    overlay.fixture = None  # a corner with a speaker but no bar
    fr = frames()
    overlay.apply(fr, patch, 0.0)
    assert all(s.intensity == 0.0 for f in fr for s in f.values())


def test_tones_land_on_their_own_output_through_the_mixer(fake_sd) -> None:  # noqa: F811
    from stargarden.audio.backends import SounddeviceBackend
    from stargarden.audio.mixer import Mixer, Voice
    from stargarden.audio.sources import ClipSource
    from stargarden.config import AudioConfig, AudioMode

    fake = fake_sd([("USB Sound Device", 8)])
    backend = SounddeviceBackend(AudioConfig(mode=AudioMode.QUAD, channel_map=(1, 2, 5, 6)))
    mixer = Mixer(48_000, {Layer.DISCRETES: 0.7})
    backend.start(mixer.render)
    stream = fake.streams[-1]
    for k in range(4):
        mixer.add(Layer.DISCRETES, Voice(f"check:{k + 1}", ClipSource(check.tone(48_000, 440.0, 0.1, 0.3)), check.Channel(k), 48_000))
        out = np.zeros((256, 8), np.float32)
        stream.kw["callback"](out, 256, None, None)
        loud = {c for c in range(8) if np.abs(out[:, c]).max() > 0.01}
        assert loud == {(1, 2, 5, 6)[k] - 1}, (k, loud)  # this corner's output only
        for _ in range(40):  # let the tone play out before the next corner
            stream.kw["callback"](out, 256, None, None)
    backend.stop()


def test_tone_is_soft_and_ramped() -> None:
    clip = check.tone(48_000, 440.0, 0.5, 0.25)
    assert clip.shape == (24_000, 1) and clip.dtype == np.float32
    assert np.abs(clip).max() == pytest.approx(0.25, abs=0.01)
    assert np.abs(clip[:10]).max() < 0.01 and np.abs(clip[-10:]).max() < 0.01
