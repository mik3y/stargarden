import random

import pytest

from stargarden.config import ConfigError, FixtureConfig, LightingConfig, LightningConfig, ProfileConfig
from stargarden.lighting.drivers import ConsoleDriver
from stargarden.lighting.engine import LightingEngine
from stargarden.lighting.fixtures import BUILTIN_PROFILES, FixtureState, Patch
from stargarden.lighting.themes import AMBIENT_THEMES, SHOW_THEMES, get_theme


def make_cfg(*fixtures: FixtureConfig, **kw) -> LightingConfig:
    return LightingConfig(driver="console", fixtures=fixtures, **kw)


def test_patch_render_profiles() -> None:
    patch = Patch.from_config(
        make_cfg(FixtureConfig("a", "dim_rgbw", 1), FixtureConfig("b", "rgb", 10), FixtureConfig("c", "rgb_strobe", 20))
    )
    frame = patch.render(
        [
            FixtureState(rgb=(1.0, 0.5, 0.5), intensity=0.5),
            FixtureState(rgb=(1.0, 0.0, 0.0), intensity=0.5),
            FixtureState(rgb=(0.0, 0.0, 1.0), intensity=1.0, strobe=1.0),
        ]
    )
    assert len(frame) == 512
    assert frame[0:5] == bytes([128, 128, 0, 0, 128])  # dimmer, r-w, g-w, b-w, w
    assert frame[9:12] == bytes([128, 0, 0])  # no dimmer: intensity folded into color
    assert frame[19:23] == bytes([0, 0, 255, 255])
    assert patch.can_flash


def test_patch_rejects_overlap_and_range() -> None:
    with pytest.raises(ConfigError, match="overlaps"):
        Patch.from_config(make_cfg(FixtureConfig("a", "rgbw", 1), FixtureConfig("b", "rgb", 4)))
    with pytest.raises(ConfigError, match="out of range"):
        Patch.from_config(make_cfg(FixtureConfig("a", "rgbw", 510)))
    with pytest.raises(ConfigError, match="unknown profile"):
        Patch.from_config(make_cfg(FixtureConfig("a", "laser", 1)))


def test_jolt_bar_fx2_simple_modes() -> None:
    patch = Patch.from_config(make_cfg(FixtureConfig("bar", "jolt_bar_fx2_9ch", 1), FixtureConfig("bar6", "jolt_bar_fx2_6ch", 10)))
    assert patch.can_flash
    idle = patch.render([FixtureState(rgb=(0.2, 0.2, 1.0), intensity=0.5), FixtureState(rgb=(1.0, 1.0, 1.0), intensity=1.0)])
    # color stays on the RGB channels (the white is a separate unit, off), 16-bit dimmer, strobe open
    assert idle[0:4] == bytes([51, 51, 255, 0])
    assert (idle[4] << 8 | idle[5]) == round(0.5 * 65535)
    assert idle[6:9] == bytes([0, 0, 0])
    assert idle[9:15] == bytes([255, 255, 255, 0, 255, 255])
    flashing = patch.render([FixtureState(rgb=(1.0, 0.0, 0.0), intensity=1.0, strobe=1.0, white=1.0), FixtureState(white=0.5)])
    assert flashing[0:4] == bytes([255, 0, 0, 255])
    assert flashing[6:9] == bytes([4, 255, 255])  # plain strobe, fastest rate/duration
    assert flashing[12] == 128  # 6CH: the white channel is the only white control


def test_jolt_bar_fx2_all_modes_have_matching_footprints() -> None:
    modes = {name: p for name, p in BUILTIN_PROFILES.items() if name.startswith("jolt_bar_fx2_")}
    assert len(modes) == 17
    for name, profile in modes.items():
        assert profile.footprint == int(name.rsplit("_", 1)[1].removesuffix("ch"))
        assert profile.zone_rows == 2 and profile.has_white_unit


def test_jolt_bar_fx2_38ch_white_unit() -> None:
    patch = Patch.from_config(make_cfg(FixtureConfig("bar", "jolt_bar_fx2_38ch", 1)))
    zones = tuple((z / 8, 0.0, 1.0 - z / 8) for z in range(8))
    frame = patch.render([FixtureState(rgb=zones[0], intensity=0.5, zones=zones)])
    assert frame[0:3] == bytes([0, 0, 255]) and frame[21:24] == bytes([223, 0, 32])  # zones 1 and 8, undimmed color
    assert (frame[24] << 8 | frame[25]) == round(0.5 * 65535)  # outer dimmer carries intensity
    assert frame[26:29] == bytes([0, 0, 0])  # outer strobe open
    assert frame[29:33] == bytes([255] * 4)  # white groups pinned full...
    assert frame[33:35] == bytes([0, 0])  # ...their dimmer carries the (zero) white level
    assert frame[35:38] == bytes([0, 0, 0])
    flash = patch.render([FixtureState(rgb=zones[0], intensity=0.5, zones=zones, white=1.0, strobe=1.0)])
    assert flash[0:3] == bytes([0, 0, 255]) and flash[26:29] == bytes([0, 0, 0])  # color untouched, RGB not strobing
    assert flash[33:38] == bytes([255, 255, 4, 255, 255])  # whites full and strobing


def test_jolt_bar_fx2_zoned_modes() -> None:
    patch = Patch.from_config(make_cfg(FixtureConfig("bar", "jolt_bar_fx2_16ch", 1), FixtureConfig("bar18", "jolt_bar_fx2_18ch", 20)))
    zones = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.5, 0.5, 0.5))
    frame = patch.render(
        [FixtureState(rgb=zones[0], intensity=0.5, zones=zones, white=0.25), FixtureState(rgb=(0.4, 0.4, 1.0), intensity=0.5, white=0.75)]
    )
    # 16CH: no dimmer, so intensity folds into the four RGB zones; the whites carry the white level
    assert frame[0:12] == bytes([128, 0, 0, 0, 128, 0, 0, 0, 128, 64, 64, 64])
    assert frame[12:16] == bytes([64] * 4)
    # 18CH: 16-bit outer dimmer at intensity, the white dimmer at the white level, both strobes open
    assert frame[19:22] == bytes([102, 102, 255])
    assert (frame[23] << 8 | frame[24]) == round(0.5 * 65535)
    assert (frame[30] << 8 | frame[31]) == round(0.75 * 65535)
    assert frame[25:28] == bytes([0, 0, 0]) and frame[32:35] == bytes([0, 0, 0])


def test_custom_profile() -> None:
    cfg = make_cfg(FixtureConfig("a", "par", 1), profiles={"par": ProfileConfig(("red", "green", "blue", "dimmer"))})
    patch = Patch.from_config(cfg)
    assert patch.render([FixtureState(rgb=(1, 1, 1), intensity=1)])[:4] == bytes([255, 255, 255, 255])


def test_themes_are_bounded_and_smooth() -> None:
    for theme in list(AMBIENT_THEMES.values()) + list(SHOW_THEMES.values()):
        prev = theme.color(0, 4, 0.0)
        for step in range(1, 200):
            c = theme.color(0, 4, step * 0.1)
            assert all(0.0 <= ch <= 1.0 for ch in c)
            assert max(abs(a - b) for a, b in zip(c, prev, strict=True)) < 0.05
            prev = c
            assert 0.0 <= theme.intensity(0, 4, step * 0.1) <= 1.0
    with pytest.raises(KeyError):
        get_theme("nope")


def test_engine_fades_and_lightning(clock) -> None:
    cfg = make_cfg(FixtureConfig("a", "dim_rgbw", 1), FixtureConfig("sky", "rgb_strobe", 10), lightning=LightningConfig(enabled=False))
    patch = Patch.from_config(cfg)
    engine = LightingEngine(patch, ConsoleDriver(), cfg, get_theme("moonlit"), random.Random(1), clock=clock)
    assert engine.frame(clock())[0].intensity == 0.0  # master starts dark
    engine.fade_master(1.0, 10.0)
    clock.advance(5)
    mid = engine.frame(clock())[0].intensity
    assert 0.3 < mid < 0.6
    clock.advance(5)
    full = engine.frame(clock())[0].intensity
    assert full > mid

    before = engine.frame(clock())[0].rgb
    engine.set_theme(get_theme("ember"), fade_s=20.0)
    clock.advance(0.1)
    just_after = engine.frame(clock())[0].rgb
    assert max(abs(a - b) for a, b in zip(before, just_after, strict=True)) < 0.05  # crossfade, not a jump
    clock.advance(30)
    engine.frame(clock())
    assert engine._prev_theme is None

    engine.trigger_lightning()
    clock.advance(0.06)
    states = engine.frame(clock())
    assert states[1].strobe == 1.0 and states[0].strobe == 0.0
    clock.advance(5)
    assert engine.frame(clock())[1].strobe == 0.0


def test_engine_lightning_flashes_white_unit_only(clock) -> None:
    cfg = make_cfg(FixtureConfig("bar", "jolt_bar_fx2_38ch", 1), lightning=LightningConfig(enabled=False))
    engine = LightingEngine(Patch.from_config(cfg), ConsoleDriver(), cfg, get_theme("moonlit"), random.Random(1), clock=clock)
    engine.fade_master(1.0, 0.0)
    clock.advance(1)
    before = engine.frame(clock())[0]
    assert before.white == 0.0 and before.strobe == 0.0
    engine.trigger_lightning()
    clock.advance(0.06)
    during = engine.frame(clock())[0]
    assert during.white == 1.0 and during.strobe == 1.0
    drift = max(abs(a - b) for za, zb in zip(during.zones, before.zones, strict=True) for a, b in zip(za, zb, strict=True))
    assert drift < 0.01  # the color program carries on underneath


def test_engine_renders_zoned_bar_as_two_row_gradient(clock) -> None:
    cfg = make_cfg(FixtureConfig("a", "dim_rgbw", 1), FixtureConfig("bar", "jolt_bar_fx2_112ch", 10))
    patch = Patch.from_config(cfg)
    engine = LightingEngine(patch, ConsoleDriver(), cfg, get_theme("aurora"), random.Random(1), clock=clock)
    engine.fade_master(1.0, 0.0)
    clock.advance(1)
    bar = engine.frame(clock())[1]
    assert len(bar.zones) == 32
    assert bar.zones[:16] == bar.zones[16:]  # bottom row mirrors the top row
    steps = [max(abs(a - b) for a, b in zip(bar.zones[z], bar.zones[z + 1], strict=True)) for z in range(15)]
    assert max(steps) < 0.15 and sum(steps) > 0.05  # a smooth, non-flat gradient along the bar
    assert bar.rgb == bar.zones[16]
    assert sum(patch.render([FixtureState(), bar])[9:105]) > 0  # the bar's 96 RGB channels are lit
