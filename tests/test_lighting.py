import random

import pytest

from stargarden.config import ConfigError, FixtureConfig, LightingConfig, ProfileConfig
from stargarden.lighting.drivers import ConsoleDriver
from stargarden.lighting.engine import LightingEngine
from stargarden.lighting.fixtures import BUILTIN_TYPES, CellState, Patch
from stargarden.lighting.themes import AMBIENT_THEMES, DRIFT_THEMES, SHOW_THEMES, ChaseTheme, Spot, TideTheme, get_theme


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


def test_themes_are_bounded_and_smooth() -> None:
    spot = Spot(0, 4, 1, 4, 0, 2, ring=1, ring_count=16)
    for theme in [*AMBIENT_THEMES.values(), *SHOW_THEMES.values(), *DRIFT_THEMES.values()]:
        prev = theme.color(spot, 0.0)
        for step in range(1, 200):
            c = theme.color(spot, step * 0.1)
            assert all(0.0 <= ch <= 1.0 for ch in c)
            if not isinstance(theme, ChaseTheme):  # the chase is meant to snap; the slow programs must not
                assert max(abs(a - b) for a, b in zip(c, prev, strict=True)) < 0.05
            prev = c
            assert 0.0 <= theme.intensity(spot, step * 0.1) <= 1.0
    with pytest.raises(KeyError):
        get_theme("nope")


def test_ember_waves_void_columns_and_palette() -> None:
    theme = get_theme("ember-waves")
    grid = {(col, row): Spot(0, 4, col, 4, row, 2) for col in range(4) for row in range(2)}
    for t in (0.0, 3.7, 8.2, 20.5):
        for (col, row), spot in grid.items():
            r, g, b = theme.color(spot, t)
            assert b <= 0.02 and r >= 0.7 and g <= 0.5 and r > g  # red through amber, never washed out
            assert theme.intensity(spot, t) == pytest.approx(theme.intensity(grid[(col, 1 - row)], t))  # a column is one unit
        for col in range(4):  # voids carry the same wave at a fraction of the light
            spot = grid[(col, 0)]
            full = theme.trough_level + (1.0 - theme.trough_level) * theme.wave(spot, t)
            assert theme.intensity(spot, t) == pytest.approx(full * theme.gate(spot, t))
    # the voids exchange: early in the cycle columns 2/4 are dark, half a cycle later 1/3 are, and it never jumps
    c1, c2 = grid[(0, 0)], grid[(1, 0)]
    assert theme.gate(c2, 1.0) == pytest.approx(theme.void_level) and theme.gate(c1, 1.0) == 1.0
    half = theme.swap_period_s / 2
    assert theme.gate(c1, half + 1.0) == pytest.approx(theme.void_level) and theme.gate(c2, half + 1.0) == 1.0
    gates = [theme.gate(c1, i * 0.1) for i in range(int(theme.swap_period_s * 10))]
    assert max(abs(a - b) for a, b in zip(gates, gates[1:], strict=False)) < 0.02
    # the wave moves: a fixed spot sees a crest and a trough within one period
    levels = [theme.intensity(grid[(0, 0)], t) for t in [i * 0.25 for i in range(60)]]
    assert max(levels) > 0.8 and min(levels) < 0.4


def test_green_tide_washes_round_the_ring_and_back() -> None:
    theme = get_theme("green-tide")
    assert isinstance(theme, TideTheme)
    n = 16
    ring = [Spot(r // 4, 4, r % 4, 4, 0, 2, ring=r, ring_count=n) for r in range(n)]
    period = theme.period_s

    def head(t: float) -> int:
        return max(range(n), key=lambda r: theme.intensity(ring[r], t))

    # out: the crest advances clockwise through the first half of the cycle, fastest in the middle
    heads = [head(period / 4 + k * 2.0) for k in range(5)]
    assert all(1 <= (b - a) % n <= 2 for a, b in zip(heads, heads[1:], strict=False)), heads
    # back: counter-clockwise through the second half
    heads = [head(3 * period / 4 + k * 2.0) for k in range(5)]
    assert all(1 <= (a - b) % n <= 2 for a, b in zip(heads, heads[1:], strict=False)), heads
    # it turns gently: the crest is still at the ends of the cycle and back where it started
    assert theme.head(ring[0], 0.0) == pytest.approx(0.0) and theme.head(ring[0], period / 2) == pytest.approx(n)
    assert abs(theme.head(ring[0], 0.5) - theme.head(ring[0], 0.0)) < 0.05
    # the rendered crest sits where head() says, and the far side of the ring is dim
    for t in (5.0, 21.0, 40.0, 58.0):
        h = theme.head(ring[0], t)
        assert min((head(t) - h) % n, (h - head(t)) % n) <= 1.0
        far = ring[int(round(h + n / 2)) % n]
        assert theme.intensity(far, t) < 0.5 < theme.intensity(ring[int(round(h)) % n], t)
    # green throughout: every column, every time, and the whole bar's height lights as one column
    for t in (0.0, 7.3, 19.0, 33.3, 50.1):
        for spot in ring:
            r, g, b = theme.color(spot, t)
            assert g > r and g > b and b <= 0.2 and g >= 0.1
            twin = Spot(spot.fixture, spot.count, spot.col, spot.cols, 1 - spot.row, spot.rows, ring=spot.ring, ring_count=n)
            assert theme.intensity(spot, t) == pytest.approx(theme.intensity(twin, t))
    # a fixed column sees the crest come and go within a cycle
    levels = [theme.intensity(ring[5], k * 0.5) for k in range(int(period * 2))]
    assert max(levels) > 0.9 and min(levels) < 0.45


def test_orbit_chases_both_ways_then_dances() -> None:
    theme = get_theme("orbit")
    assert isinstance(theme, ChaseTheme)
    n = 16
    ring = [Spot(r // 4, 4, r % 4, 4, 0, 2, ring=r, ring_count=n) for r in range(n)]
    chase = theme.laps * n * theme.step_s

    def head(t: float) -> int:
        return max(range(n), key=lambda r: theme.intensity(ring[r], t))

    # clockwise: the brightest column advances one place per step
    heads = [head(2.2 + k * theme.step_s) for k in range(6)]
    assert all((b - a) % n == 1 for a, b in zip(heads, heads[1:], strict=False)), heads
    # counter-clockwise, well inside the second movement
    heads = [head(chase + 2.2 + k * theme.step_s) for k in range(6)]
    assert all((a - b) % n == 1 for a, b in zip(heads, heads[1:], strict=False)), heads
    # a lit head is bright, the far side of the room is only the glow
    t = 2.0  # exactly on a step: the head sits squarely on one column
    h = head(t)
    assert theme.intensity(ring[h], t) > 0.9 and theme.intensity(ring[(h + 8) % n], t) == pytest.approx(theme.glow_level)
    r, g, b = theme.color(ring[h], t)
    assert b > 0.9 and g < 0.3  # blue/purple, never washed
    # the dance: odd and even columns take turns each beat
    t0 = 2 * chase + 3.0
    even = [theme.intensity(ring[0], t0 + k * theme.dance_step_s) for k in range(4)]
    odd = [theme.intensity(ring[1], t0 + k * theme.dance_step_s) for k in range(4)]
    assert all((e > 0.8) != (o > 0.8) for e, o in zip(even, odd, strict=True))
    assert (even[0] > 0.8) != (even[1] > 0.8)
    # movements cross-fade rather than cut: at each boundary the two sides share the light equally
    cycle = theme._cycle_s(ring[0])
    assert theme._weights(ring[0], chase) == pytest.approx((0.5, 0.5, 0.0))
    assert theme._weights(ring[0], 2 * chase) == pytest.approx((0.0, 0.5, 0.5))
    assert theme._weights(ring[0], cycle) == pytest.approx((0.5, 0.0, 0.5))
    assert all(sum(theme._weights(ring[0], k / 10)) == pytest.approx(1.0) for k in range(int(cycle * 10)))


def test_spot_grid_and_ring_from_bar_cells(clock) -> None:
    cfg = make_cfg(fx("bar", "jolt_bar_fx2", "38ch", 1), fx("wash", "generic", "rgb", 40))
    engine = LightingEngine(Patch.from_config(cfg), ConsoleDriver(), cfg, get_theme("ember-waves"), random.Random(1), clock=clock)
    bar, wash = engine._spots
    assert bar["rgb1"] == Spot(0, 2, 0, 4, 0, 2, 0, 5) and bar["rgb5"] == Spot(0, 2, 0, 4, 1, 2, 0, 5)
    assert bar["rgb8"] == Spot(0, 2, 3, 4, 1, 2, 3, 5)
    assert wash["cell"] == Spot(1, 2, ring=4, ring_count=5) and wash["cell"].index == 1.0
    clock.t = 0.0  # start of the exchange cycle: columns 1/3 hold the light
    engine.fade_master(1.0, 0.0)
    frame = engine.frame(clock())[0]
    assert frame["rgb1"].intensity == pytest.approx(frame["rgb5"].intensity)  # a column's two rows match
    assert frame["rgb2"].intensity < 0.1 * frame["rgb1"].intensity  # column 2 is a void


def test_ring_runs_clockwise_from_north_by_position() -> None:
    cfg = make_cfg(
        FixtureConfig("nw", "generic", 1, "rgb", (-0.8, 0.8)),
        FixtureConfig("ne", "generic", 4, "rgb", (0.8, 0.8)),
        FixtureConfig("sw", "generic", 7, "rgb", (-0.8, -0.8)),
        FixtureConfig("se", "generic", 10, "rgb", (0.8, -0.8)),
    )
    engine = LightingEngine(Patch.from_config(cfg), ConsoleDriver(), cfg, get_theme("orbit"), random.Random(1))
    assert [s["cell"].ring for s in engine._spots] == [3, 0, 2, 1]  # ne, se, sw, nw going clockwise from north


def test_washes_render_unchanged(clock) -> None:
    """Four washes and a bar (the original dev rig) must render byte-for-byte what the previous fixture model produced."""
    cfg = make_cfg(
        fx("tree-nw", "generic", "dim_rgbw", 1),
        fx("tree-ne", "generic", "dim_rgbw", 6),
        fx("tree-sw", "generic", "dim_rgbw", 11),
        fx("tree-se", "generic", "dim_rgbw", 16),
        fx("sky", "jolt_bar_fx2", "38ch", 21),
    )
    patch = Patch.from_config(cfg)
    clock.t = 1234.5
    engine = LightingEngine(patch, ConsoleDriver(), cfg, get_theme("moonlit"), random.Random(1), clock=clock)
    engine.fade_master(1.0, 0.0)
    frame = patch.render(engine.frame(clock()))
    washes = b"".join(frame[f.address - 1 : f.address + 4] for f in patch.fixtures[:4])
    assert washes == bytes([188, 0, 73, 132, 5, 217, 0, 64, 121, 44, 191, 0, 7, 105, 70, 198, 13, 0, 115, 19])
    sky = patch.fixtures[4].address - 1
    bar = frame[sky : sky + 38]  # jolt 38ch: 8 lit RGB zones, outer dimmer full, both shutters open, whites dark
    assert sum(bar[0:24]) > 0 and bar[24] > 150 and bar[26:29] == bytes([0, 0, 0])  # theme intensity on the outer dimmer
    assert bar[29:38] == bytes(9)


def test_peak_caps_themes_but_not_lightning(clock) -> None:
    from stargarden.lightning import StrikeOverlay, compose_strike

    cfg = make_cfg(fx("a", "generic", "dim_rgbw", 1), fx("sky", "jolt_bar_fx2", "38ch", 10), peak=0.5)
    patch = Patch.from_config(cfg)
    engine = LightingEngine(patch, ConsoleDriver(), cfg, get_theme("moonlit"), random.Random(1), clock=clock)
    engine.fade_master(1.0, 0.0)
    clock.advance(1)
    half = engine.frame(clock())[0]["cell"].intensity
    engine.set_peak(1.0)
    assert engine.frame(clock())[0]["cell"].intensity == pytest.approx(half * 2)
    assert engine.nudge_peak(-0.3) == pytest.approx(0.7) and engine.nudge_peak(-2.0) == 0.0
    assert engine.frame(clock())[0]["cell"].intensity == 0.0

    engine.set_peak(0.2)
    strike = compose_strike(random.Random(5), {"a": (-0.8, 0.8), "sky": (0.8, 0.8)}, "sky", (0.3, 2.5))
    engine.add_overlay(StrikeOverlay(strike, clock()))
    clock.advance(next(f.start for f in strike.flashes["sky"] if f.level == 1.0) + 0.01)
    frames = engine.frame(clock())
    assert frames[1]["w1"].intensity == 1.0  # the flash ignores the peak
    assert frames[1]["rgb1"].intensity <= 0.2


def test_engine_fades(clock) -> None:
    cfg = make_cfg(fx("a", "generic", "dim_rgbw", 1), fx("sky", "generic", "rgb_strobe", 10))
    patch = Patch.from_config(cfg)
    engine = LightingEngine(patch, ConsoleDriver(), cfg, get_theme("moonlit"), random.Random(1), clock=clock)
    assert engine.frame(clock())[0]["cell"].intensity == 0.0  # master starts dark
    engine.fade_master(1.0, 10.0)
    clock.advance(5)
    mid = engine.frame(clock())[0]["cell"].intensity
    assert 0.3 < mid < 0.6
    clock.advance(5)
    assert engine.frame(clock())[0]["cell"].intensity > mid

    before = engine.frame(clock())[0]["cell"].color
    engine.set_theme(get_theme("ember"), fade_s=20.0)
    clock.advance(0.1)
    just_after = engine.frame(clock())[0]["cell"].color
    assert max(abs(a - b) for a, b in zip(before, just_after, strict=True)) < 0.05  # crossfade, not a jump
    clock.advance(30)
    engine.frame(clock())
    assert engine._prev_theme is None


def test_tempo_scales_a_show_theme_without_a_jump(clock) -> None:
    cfg = make_cfg(
        FixtureConfig("nw", "generic", 1, "rgb", (-0.8, 0.8)),
        FixtureConfig("ne", "generic", 4, "rgb", (0.8, 0.8)),
        FixtureConfig("sw", "generic", 7, "rgb", (-0.8, -0.8)),
        FixtureConfig("se", "generic", 10, "rgb", (0.8, -0.8)),
    )
    patch = Patch.from_config(cfg)
    orbit = get_theme("orbit")
    assert orbit.tempo_bpm == 120.0 and get_theme("ember-waves").tempo_bpm is None
    engine = LightingEngine(patch, ConsoleDriver(), cfg, orbit, random.Random(1), clock=clock)
    engine.fade_master(1.0, 0.0)
    clock.t = 1000.0
    assert engine.theme_time(1000.0) == 1000.0  # no tempo: the theme runs on the engine's clock

    engine.set_tempo(60.0)  # half speed
    assert engine.tempo == 60.0
    assert engine.theme_time(1004.0) == 1002.0
    clock.t = 1004.0
    slowed = engine.frame(clock())
    engine.set_tempo(None)
    assert engine.theme_time(1004.0) == 1002.0  # released: rate 1× from here, no jump
    assert engine.theme_time(1005.0) == 1003.0
    engine.set_tempo(240.0)
    assert engine.theme_time(1005.0) == 1004.0
    engine.set_tempo(None)

    plain = LightingEngine(patch, ConsoleDriver(), cfg, orbit, random.Random(1), clock=clock)
    plain.fade_master(1.0, 0.0)
    assert slowed == plain.frame(1002.0)  # what the slowed theme showed at 1004 is what it shows unslowed at 1002

    engine.set_theme(get_theme("ember-waves"), fade_s=0.0)  # not written at a tempo: unaffected
    clock.t = 1100.0
    engine.frame(clock())
    before = engine.theme_time(1110.0)
    engine.set_tempo(70.0)
    assert engine.theme_time(1110.0) == before
    with pytest.raises(ValueError):
        engine.set_tempo(0.0)


# -- ADJ Jolt Bar FX2 -------------------------------------------------------------


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


def test_engine_renders_bar_as_two_row_gradient(clock) -> None:
    cfg = make_cfg(fx("a", "generic", "dim_rgbw", 1), fx("bar", "jolt_bar_fx2", "112ch", 10))
    patch = Patch.from_config(cfg)
    engine = LightingEngine(patch, ConsoleDriver(), cfg, get_theme("moonlit"), random.Random(1), clock=clock)
    engine.fade_master(1.0, 0.0)
    clock.advance(1)
    frames = engine.frame(clock())
    bar = frames[1]
    top = [bar[f"rgb{i}"].color for i in range(1, 17)]
    assert top == [bar[f"rgb{i}"].color for i in range(17, 33)]  # bottom row mirrors the top row
    steps = [max(abs(a - b) for a, b in zip(top[z], top[z + 1], strict=True)) for z in range(15)]
    assert max(steps) < 0.15 and sum(steps) > 0.05  # a smooth, non-flat gradient along the bar
    assert sum(patch.render(frames)[9:105]) > 0  # the bar's 96 RGB channels are lit
