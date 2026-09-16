import asyncio
import random
from pathlib import Path

import pytest

from stargarden.config import FixtureConfig, LightingConfig, LightningConfig
from stargarden.lighting.drivers import ConsoleDriver
from stargarden.lighting.engine import LightingEngine
from stargarden.lighting.fixtures import Patch
from stargarden.lighting.themes import get_theme
from stargarden.lightning import Lightning, StrikeOverlay, compose_strike
from stargarden.manifest import DiscreteEntry, Manifest

POSITIONS = {"nw": (-0.8, 0.8), "ne": (0.8, 0.8), "sw": (-0.8, -0.8), "se": (0.8, -0.8)}


def test_strike_ripples_outward_from_the_origin() -> None:
    strike = compose_strike(random.Random(3), POSITIONS, "nw", (0.3, 2.5))
    assert strike.origin == "nw" and strike.position == (-0.8, 0.8)
    first = {name: min(f.start for f in fs) for name, fs in strike.flashes.items()}
    peak = {name: max(f.level for f in fs) for name, fs in strike.flashes.items()}
    assert first["nw"] <= first["ne"] < first["se"]  # neighbors flash after the origin, the far corner last
    assert peak["nw"] == 1.0 and peak["ne"] < 1.0 and peak["se"] < peak["ne"]
    assert 0.3 <= strike.thunder_delay <= 2.5
    assert strike.duration == max(f.end for fs in strike.flashes.values() for f in fs) > 0.3  # includes the afterglow


def test_successive_strikes_differ() -> None:
    rng = random.Random(7)
    a = compose_strike(rng, POSITIONS, "ne", (0.3, 2.5))
    b = compose_strike(rng, POSITIONS, "ne", (0.3, 2.5))
    assert a.flashes["ne"] != b.flashes["ne"]
    assert a.thunder_delay != b.thunder_delay


def make_patch() -> tuple[LightingConfig, Patch]:
    cfg = LightingConfig(
        driver="console",
        fixtures=(
            FixtureConfig("nw", "generic", 1, "dim_rgbw", (-0.8, 0.8)),
            FixtureConfig("sky", "jolt_bar_fx2", 10, "38ch", (0.8, 0.8)),
        ),
    )
    return cfg, Patch.from_config(cfg)


def test_overlay_flashes_whites_or_color_and_expires(clock) -> None:
    cfg, patch = make_patch()
    engine = LightingEngine(patch, ConsoleDriver(), cfg, get_theme("moonlit"), random.Random(1), clock=clock)
    engine.fade_master(1.0, 0.0)
    clock.advance(1)
    quiet = engine.frame(clock())
    strike = compose_strike(random.Random(5), {"nw": (-0.8, 0.8), "sky": (0.8, 0.8)}, "sky", (0.3, 2.5))
    engine.add_overlay(StrikeOverlay(strike, clock()))
    peak_at = next(f.start for f in strike.flashes["sky"] if f.level == 1.0) + 0.01
    clock.advance(peak_at)
    frames = engine.frame(clock())
    assert all(frames[1][f"w{j}"].intensity == 1.0 for j in range(1, 5))  # the bar's whites flash
    assert frames[1]["rgb1"].color == pytest.approx(engine.frame(clock())[1]["rgb1"].color)  # its color program carries on
    ripple = [f for f in strike.flashes["nw"] if f.start <= peak_at < f.end]
    if ripple:  # the wash has no whites: its color is pushed toward white, dimmer than the origin
        assert frames[0]["cell"].color[2] > quiet[0]["cell"].color[2] and frames[0]["cell"].intensity < 1.0
    clock.advance(strike.duration + 1)
    frames = engine.frame(clock())
    assert all(frames[1][f"w{j}"].intensity == 0.0 for j in range(1, 5))
    assert engine._overlays == []


class FakeAudio:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[float, float], float]] = []

    def play_thunder(self, entry: DiscreteEntry, origin: tuple[float, float], gain: float = 1.0) -> None:
        self.calls.append((entry.path.name, origin, gain))


def make_lightning(clock, cfg: LightningConfig, allowed=lambda: True) -> tuple[Lightning, FakeAudio, LightingEngine]:
    lcfg, patch = make_patch()
    engine = LightingEngine(patch, ConsoleDriver(), lcfg, get_theme("moonlit"), random.Random(1), clock=clock)
    thunder = tuple(DiscreteEntry(Path(f"/x/{n}.wav")) for n in ("boom", "roll"))
    manifest = Manifest(Path("/x"), (), (), (), thunder)
    audio = FakeAudio()
    return Lightning(cfg, patch, engine, audio, manifest, random.Random(2), allowed=allowed, clock=clock), audio, engine  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_strike_schedules_thunder_at_the_origin(clock) -> None:
    lightning, audio, engine = make_lightning(clock, LightningConfig(thunder_delay_s=(0.05, 0.1)))
    strike = lightning.strike("sky")
    assert strike is not None and engine._overlays
    await asyncio.sleep(0.15)
    assert len(audio.calls) == 1
    name, origin, gain = audio.calls[0]
    assert origin == (0.8, 0.8) and 0.5 <= gain <= 1.0
    second = lightning.strike()
    assert second is not None and second.origin == "nw"  # never the same tree twice in a row
    await asyncio.sleep(0.15)
    assert audio.calls[1][0] != name  # nor the same thunder twice in a row


def test_scheduler_waits_at_least_the_minimum(clock) -> None:
    lightning, _, _ = make_lightning(clock, LightningConfig(mean_interval_s=1200, min_interval_s=300))
    assert lightning.time_to_next() >= 300
    off, _, _ = make_lightning(clock, LightningConfig(enabled=False))
    assert off.time_to_next() is None
