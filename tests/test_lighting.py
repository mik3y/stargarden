import pytest

from stargarden.config import ConfigError, FixtureConfig, LightingConfig, ProfileConfig
from stargarden.lighting.drivers import ConsoleDriver
from stargarden.lighting.engine import LightingEngine
from stargarden.lighting.fixtures import BUILTIN_TYPES, CellState, Patch
from stargarden.sunset import Sunset


def make_cfg(*fixtures: FixtureConfig, **kw) -> LightingConfig:
    return LightingConfig(driver="console", fixtures=fixtures, **kw)


def fx(name: str, type_: str, mode: str, address: int) -> FixtureConfig:
    return FixtureConfig(name=name, type=type_, address=address, mode=mode)


def cell(color=(0.0, 0.0, 0.0), intensity: float = 1.0, strobe: float = 0.0) -> dict[str, CellState]:
    return {"cell": CellState(color, intensity, strobe)}


def test_generic_modes_render() -> None:
    patch = Patch.from_config(
        make_cfg(fx("a", "generic", "dim_rgbw", 1), fx("b", "generic", "rgb", 10), fx("c", "generic", "rgb_strobe", 20))
    )
    frame = patch.render([cell((1.0, 0.5, 0.5), 0.5), cell((1.0, 0.0, 0.0), 0.5), cell((0.0, 0.0, 1.0), 1.0, strobe=1.0)])
    assert len(frame) == 512
    assert frame[0:5] == bytes([128, 128, 0, 0, 128])  # dimmer, then r-w, g-w, b-w, w
    assert frame[9:12] == bytes([128, 0, 0])  # no dimmer: intensity folded into color
    assert frame[19:23] == bytes([0, 0, 255, 255])  # single-channel strobe at full rate
    assert patch.can_flash


def test_patch_rejects_bad_config() -> None:
    with pytest.raises(ConfigError, match="overlaps"):
        Patch.from_config(make_cfg(fx("a", "generic", "rgbw", 1), fx("b", "generic", "rgb", 4)))
    with pytest.raises(ConfigError, match="out of range"):
        Patch.from_config(make_cfg(fx("a", "generic", "rgbw", 510)))
    with pytest.raises(ConfigError, match="unknown fixture type"):
        Patch.from_config(make_cfg(fx("a", "laser", "", 1)))
    with pytest.raises(ConfigError, match="no mode"):
        Patch.from_config(make_cfg(fx("a", "generic", "octo", 1)))
    with pytest.raises(ConfigError, match="pick one"):
        Patch.from_config(make_cfg(fx("a", "jolt_bar_fx2", "", 1)))


def test_custom_profile_is_a_single_mode_type() -> None:
    cfg = make_cfg(fx("a", "par", "", 1), profiles={"par": ProfileConfig(("red", "green", "blue", "dimmer"))})
    patch = Patch.from_config(cfg)
    assert patch.render([cell((1, 1, 1), 1)])[:4] == bytes([255, 255, 255, 255])
    with pytest.raises(ConfigError, match="dimmer_fine"):
        Patch.from_config(make_cfg(fx("a", "bad", "", 1), profiles={"bad": ProfileConfig(("dimmer_fine",))}))


def test_jolt_bar_fx2_all_modes() -> None:
    modes = BUILTIN_TYPES["jolt_bar_fx2"].modes
    assert len(modes) == 17
    for name, mode in modes.items():
        assert mode.footprint == int(name.removesuffix("ch"))
        assert mode.white_cells and mode.color_cells and mode.can_flash
        for cells in (mode.color_cells, mode.white_cells):
            assert len({c.position for c in cells}) == len(cells)  # every cell of a kind has its own spot


def test_jolt_bar_fx2_simple_modes() -> None:
    patch = Patch.from_config(make_cfg(fx("bar", "jolt_bar_fx2", "9ch", 1), fx("bar6", "jolt_bar_fx2", "6ch", 10)))
    idle = patch.render(
        [
            {"rgb1": CellState((0.2, 0.2, 1.0), 0.5), "w1": CellState(intensity=0.0)},
            {"rgb1": CellState((1.0, 1.0, 1.0), 1.0), "w1": CellState(intensity=0.5)},
        ]
    )
    # 9CH: color undimmed on RGB, white off, the shared 16-bit dimmer carries the intensity, shutter open
    assert idle[0:9] == bytes([51, 51, 255, 0, 128, 0, 0, 0, 0])
    # 6CH: the white is mastered by the shared dimmer (at full), so its channel is the white level
    assert idle[9:15] == bytes([255, 255, 255, 128, 255, 255])
    flash = patch.render(
        [{"rgb1": CellState((1.0, 0.0, 0.0), 1.0), "w1": CellState(intensity=1.0, strobe=1.0)}, {"rgb1": CellState(), "w1": CellState()}]
    )
    assert flash[0:9] == bytes([255, 0, 0, 255, 255, 255, 5, 255, 255])  # shutter "Strobe" (3–5) at full rate/duration


def test_jolt_bar_fx2_38ch_white_unit() -> None:
    patch = Patch.from_config(make_cfg(fx("bar", "jolt_bar_fx2", "38ch", 1)))
    frame = {f"rgb{z + 1}": CellState((z / 8, 0.0, 1.0 - z / 8), 0.5) for z in range(8)}
    frame |= {f"w{j}": CellState(intensity=0.0) for j in range(1, 5)}
    out = patch.render([frame])
    assert out[0:3] == bytes([0, 0, 255]) and out[21:24] == bytes([223, 0, 32])  # zones 1 and 8, undimmed color
    assert out[24:26] == bytes([128, 0])  # outer 16-bit dimmer carries the intensity
    assert out[26:29] == bytes([0, 0, 0])  # outer shutter open
    assert out[29:38] == bytes(9)  # white groups, white dimmer, white shutter all dark

    for j in range(1, 5):
        frame[f"w{j}"] = CellState(intensity=1.0, strobe=1.0)
    out = patch.render([frame])
    assert out[0:3] == bytes([0, 0, 255]) and out[26:29] == bytes([0, 0, 0])  # color untouched, RGB not strobing
    assert out[29:38] == bytes([255, 255, 255, 255, 255, 255, 5, 255, 255])  # whites full and strobing

    frame["w1"], frame["w2"], frame["w3"], frame["w4"] = (CellState(intensity=i) for i in (1.0, 0.5, 0.0, 0.0))
    out = patch.render([frame])
    assert out[29:35] == bytes([255, 128, 0, 0, 255, 255])  # mastered cells: relative levels, dimmer at the brightest


def test_jolt_bar_fx2_zoned_modes() -> None:
    patch = Patch.from_config(make_cfg(fx("bar", "jolt_bar_fx2", "16ch", 1), fx("bar18", "jolt_bar_fx2", "18ch", 20)))
    zones = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.5, 0.5, 0.5))
    f16 = {f"rgb{i + 1}": CellState(c, 0.5) for i, c in enumerate(zones)} | {f"w{j}": CellState(intensity=0.25) for j in range(1, 5)}
    f18 = {"rgb1": CellState((0.4, 0.4, 1.0), 0.5), "w1": CellState(intensity=0.75)}
    out = patch.render([f16, f18])
    # 16CH has no dimmers: intensity folds into the four RGB zones and the whites carry their own level
    assert out[0:12] == bytes([128, 0, 0, 0, 128, 0, 0, 0, 128, 64, 64, 64])
    assert out[12:16] == bytes([64] * 4)
    # 18CH: RGB undimmed with a 16-bit outer dimmer; the white has no channel of its own, only its dimmer
    assert out[19:22] == bytes([102, 102, 255])
    assert out[23:25] == bytes([128, 0]) and out[25:28] == bytes([0, 0, 0])
    assert out[30:32] == bytes([191, 255]) and out[32:35] == bytes([0, 0, 0])


def bars() -> LightingConfig:
    return make_cfg(*(fx(f"bar-{k + 1}", "jolt_bar_fx2", "38ch", 1 + 38 * k) for k in range(4)), peak=0.5)


def test_engine_shows_one_look_on_every_bar(clock) -> None:
    cfg = bars()
    patch = Patch.from_config(cfg)
    sunset = Sunset(leg_s=100.0, dusk_level=0.4, clock=clock)
    engine = LightingEngine(patch, ConsoleDriver(), cfg, sunset.look, clock=clock)
    assert all(s.intensity == 0.0 for s in engine.frame(clock())[0].values())  # master starts dark
    engine.fade_master(1.0, 10.0)
    clock.advance(5)
    assert engine.frame(clock())[0]["rgb1"].intensity == pytest.approx(0.5 * 0.5 * sunset.look()[1])  # half faded, under the peak
    clock.advance(45)
    frames = engine.frame(clock())
    color, level = sunset.look()
    assert sunset.position == pytest.approx(0.5) and level == pytest.approx(0.7)
    for frame in frames:
        assert all(frame[f"rgb{i}"].color == color and frame[f"rgb{i}"].intensity == pytest.approx(level * 0.5) for i in range(1, 9))
        assert all(frame[f"w{j}"].intensity == 0.0 for j in range(1, 5))  # no white in a sunset
    universe = patch.render(frames)
    assert universe[0:38] == universe[38:76] == universe[76:114] == universe[114:152]  # four identical bars
    assert universe[0:3] == bytes([255, 10, 0])  # red, halfway
    engine.set_peak(1.0)
    assert engine.frame(clock())[0]["rgb1"].intensity == pytest.approx(level)
    engine.fade_master(0.0, 0.0)
    assert engine.frame(clock())[0]["rgb1"].intensity == 0.0
