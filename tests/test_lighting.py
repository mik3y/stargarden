import pytest

from stargarden.config import ConfigError, FixtureConfig, FixtureRole, LightingConfig, ProfileConfig, SpotColor
from stargarden.lighting.drivers import ConsoleDriver
from stargarden.lighting.engine import LightingEngine
from stargarden.lighting.fixtures import BUILTIN_TYPES, CellState, Patch
from stargarden.patterns import PATTERNS
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


def bars(**kw) -> LightingConfig:
    """The event rig: four bars and the pair of pin spots on one address."""
    spots = FixtureConfig(name="pinspots", type="pinspot_q1z", address=161, mode="4ch", role=FixtureRole.SPOT)
    return make_cfg(*(fx(f"bar-{k + 1}", "jolt_bar_fx2", "38ch", 1 + 38 * k) for k in range(4)), spots, **kw)


def test_pinspot_q1z_personalities() -> None:
    modes = BUILTIN_TYPES["pinspot_q1z"].modes
    assert {name: mode.footprint for name, mode in modes.items()} == {"4ch": 4, "6ch": 6, "7ch": 7}
    patch = Patch.from_config(
        make_cfg(fx("a", "pinspot_q1z", "4ch", 1), fx("b", "pinspot_q1z", "6ch", 10), fx("c", "pinspot_q1z", "7ch", 20))
    )
    white, pink = cell((1.0, 1.0, 1.0), 0.5), cell((1.0, 0.0, 0.5), 0.5)
    out = patch.render([white, white, white])
    assert out[0:4] == bytes([0, 0, 0, 128])  # 4CH: white is the white LED alone, dimmed in its own channel
    assert out[9:15] == bytes([0, 0, 0, 255, 128, 0])  # 6CH: R G B W, dimmer, strobe off
    assert out[19:26] == bytes([0, 128, 0, 0, 0, 0, 255])  # 7CH: no program, dimmer, strobe off, R G B W
    out = patch.render([pink, pink, cell((1.0, 0.0, 0.5), 1.0, strobe=1.0)])
    assert out[0:4] == bytes([128, 0, 64, 0]) and out[9:15] == bytes([255, 0, 128, 0, 128, 0])
    assert out[19:26] == bytes([0, 255, 254, 255, 0, 128, 0])  # the strobe channel's fast end


def test_engine_shows_one_sunset_on_every_bar(clock) -> None:
    cfg = bars(peak=0.5)
    patch = Patch.from_config(cfg)
    sunset = Sunset(leg_s=100.0, dusk_level=0.4, clock=clock)
    engine = LightingEngine(patch, ConsoleDriver(), cfg, sunset, clock=clock)
    assert all(s.intensity == 0.0 for s in engine.frame(clock())[0].values())  # master starts dark
    engine.fade_master(1.0, 10.0)
    clock.advance(5)
    assert engine.frame(clock())[0]["rgb1"].intensity == pytest.approx(0.5 * 0.5 * sunset.look()[1])  # half faded, under the peak
    clock.advance(45)
    frames = engine.frame(clock())
    color, level = sunset.look()
    assert sunset.position == pytest.approx(0.5) and level == pytest.approx(0.7)
    for frame in frames[:4]:
        assert all(frame[f"rgb{i}"].color == color and frame[f"rgb{i}"].intensity == pytest.approx(level * 0.5) for i in range(1, 9))
        assert all(frame[f"w{j}"].intensity == 0.0 for j in range(1, 5))  # no white in a sunset
    universe = patch.render(frames)
    assert universe[0:38] == universe[38:76] == universe[76:114] == universe[114:152]  # four identical bars
    assert universe[0:3] == bytes([255, 10, 0])  # red, halfway
    engine.set_peak(1.0)
    assert engine.frame(clock())[0]["rgb1"].intensity == pytest.approx(level)
    engine.fade_master(0.0, 0.0)
    assert engine.frame(clock())[0]["rgb1"].intensity == 0.0


def test_pin_spots_hold_their_own_level_and_color(clock) -> None:
    cfg = bars(peak=0.2)
    patch = Patch.from_config(cfg)
    sunset = Sunset(leg_s=100.0, clock=clock)
    engine = LightingEngine(patch, ConsoleDriver(), cfg, sunset, clock=clock)
    engine.fade_master(1.0, 0.0)
    clock.advance(50)
    spot = engine.frame(clock())[4]["cell"]
    assert (spot.color, spot.intensity) == ((1.0, 1.0, 1.0), 1.0)  # white at full, whatever the bars' peak
    assert patch.render(engine.last_frames)[160:164] == bytes([0, 0, 0, 255])
    engine.set_spot_level(0.5)
    engine.spot_color = SpotColor.MATCH
    spot = engine.frame(clock())[4]["cell"]
    assert spot.color == sunset.look()[0] and spot.intensity == 0.5  # the sunset's color, not its dimming
    engine.fade_master(0.0, 0.0)
    assert engine.frame(clock())[4]["cell"].intensity == 0.0  # off with the rest


def test_programs_crossfade_and_the_tempo_never_jumps_a_pattern(clock) -> None:
    cfg = bars()
    patch = Patch.from_config(cfg)
    sunset = Sunset(leg_s=100.0, clock=clock)
    engine = LightingEngine(patch, ConsoleDriver(), cfg, sunset, clock=clock)
    engine.fade_master(1.0, 0.0)
    engine.spot_color = SpotColor.MATCH
    before = engine.frame(clock())
    engine.set_program(PATTERNS["chase"], fade_s=4.0)
    clock.advance(0.05)
    after = engine.frame(clock())
    for was, now in zip(before, after, strict=True):
        for name in was:
            a, b = was[name], now[name]
            lit = [abs(x * a.intensity - y * b.intensity) for x, y in zip(a.color, b.color, strict=True)]
            assert max(lit) < 0.05, name  # a crossfade, not a cut, on the bars and the spots alike
    clock.advance(5)
    frames = engine.frame(clock())
    assert engine._prev_program is None
    assert len({(s.color, round(s.intensity, 3)) for s in frames[0].values()}) > 2  # the bar is in blocks now
    assert frames[4]["cell"].color == PATTERNS["chase"].accent(engine.beat(clock()))

    assert engine.tempo == 100.0
    clock.advance(60)
    assert engine.beat(clock()) == pytest.approx(65.05 * 100 / 60)
    beat = engine.beat(clock())
    engine.set_tempo(160.0)
    assert engine.beat(clock()) == beat  # the pattern stays where it was
    clock.advance(3)
    assert engine.beat(clock()) == pytest.approx(beat + 8)
    with pytest.raises(ValueError):
        engine.set_tempo(500)
