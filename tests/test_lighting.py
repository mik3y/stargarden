import random

import pytest

from stargarden.config import ConfigError, FixtureConfig, LightingConfig, LightningConfig
from stargarden.lighting.drivers import ConsoleDriver
from stargarden.lighting.engine import LightingEngine
from stargarden.lighting.fixtures import FixtureState, Patch
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
    assert patch.has_strobe


def test_patch_rejects_overlap_and_range() -> None:
    with pytest.raises(ConfigError, match="overlaps"):
        Patch.from_config(make_cfg(FixtureConfig("a", "rgbw", 1), FixtureConfig("b", "rgb", 4)))
    with pytest.raises(ConfigError, match="out of range"):
        Patch.from_config(make_cfg(FixtureConfig("a", "rgbw", 510)))
    with pytest.raises(ConfigError, match="unknown profile"):
        Patch.from_config(make_cfg(FixtureConfig("a", "laser", 1)))


def test_custom_profile() -> None:
    cfg = make_cfg(FixtureConfig("a", "par", 1), profiles={"par": ("red", "green", "blue", "dimmer")})
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
