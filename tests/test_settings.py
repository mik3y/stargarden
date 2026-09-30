"""Timing settings from the console: live, persisted, and back to the config on reset."""

import asyncio
import json
from pathlib import Path

import pytest

from conftest import FakeClock
from stargarden.app import SETTINGS, Stargarden
from stargarden.config import LightningConfig
from stargarden.console import ActionError, Console, install_log_buffer
from stargarden.manifest import load_manifest
from stargarden.state import Overrides, StateStore
from test_app import make_config
from test_lightning import make_lightning


def program(tmp_path: Path, assets: Path) -> Stargarden:
    config = make_config(tmp_path, assets)
    p = Stargarden(config, load_manifest(config.assets_root), seed=1)
    p.conductor.set_night(True)
    return p


def test_settings_persist_only_when_they_differ_from_the_config(tmp_path: Path, assets: Path) -> None:
    store = StateStore(tmp_path / "s.json")
    store.save(Overrides(settings={"lightning.mean_interval_s": 90.0}))
    assert json.loads(store.path.read_text()) == {"settings": {"lightning.mean_interval_s": 90.0}}
    assert store.load() == Overrides(settings={"lightning.mean_interval_s": 90.0})
    store.path.write_text('{"settings": {"lightning.mean_interval_s": "soon"}}')
    assert store.load() == Overrides()

    p = program(tmp_path, assets)
    console = Console(p, install_log_buffer("INFO"))
    defaults = p.setting_defaults()
    assert list(defaults) == list(SETTINGS) and [s.name for s in console.status().settings] == list(SETTINGS)
    assert defaults["discretes.min_interval_s"] == 40.0 and defaults["lightning.mean_interval_s"] == 200.0
    assert p.audio.discretes_interval_s == (40.0, 90.0) and p.lightning.intervals_s == (200.0, 150.0)

    assert console.act("set_setting", {"name": "lightning.mean_interval_s", "value": 90}) == 90.0
    assert console.act("set_setting", {"name": "discretes.max_interval_s", "value": 120.5}) == 120.5
    assert p.lightning.intervals_s == (90.0, 150.0) and p.audio.discretes_interval_s == (40.0, 120.5)
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["settings"] == {"discretes.max_interval_s": 120.5, "lightning.mean_interval_s": 90.0}
    status = {s.name: s for s in console.status().settings}
    assert (status["lightning.mean_interval_s"].value, status["lightning.mean_interval_s"].default) == (90.0, 200.0)

    console.act("set_setting", {"name": "lightning.mean_interval_s", "value": 200})  # back to the default: no override kept
    assert "lightning.mean_interval_s" not in json.loads((tmp_path / "state.json").read_text())["settings"]

    again = program(tmp_path, assets)
    assert again.audio.discretes_interval_s == (40.0, 120.5) and again.lightning.intervals_s == (200.0, 150.0)
    again.reset_overrides()
    assert again.audio.discretes_interval_s == (40.0, 90.0) and not (tmp_path / "state.json").exists()


def test_settings_are_validated_and_bad_pairs_are_rolled_back(tmp_path: Path, assets: Path) -> None:
    p = program(tmp_path, assets)
    console = Console(p, install_log_buffer("INFO"))
    for bad in ({"name": "lightning.mean_interval_s", "value": 0}, {"name": "lightning.mean_interval_s", "value": "soon"}):
        with pytest.raises(ActionError):
            console.act("set_setting", bad)
    with pytest.raises(ActionError, match="unknown setting"):
        console.act("set_setting", {"name": "timers.show_delay_s", "value": 5})
    with pytest.raises(ActionError, match="min <= max"):
        console.act("set_setting", {"name": "discretes.min_interval_s", "value": 500})  # above the max
    assert p.audio.discretes_interval_s == (40.0, 90.0) and p.overrides.settings == {}
    with pytest.raises(ActionError):
        console.act("set_setting", {"name": "discretes.min_interval_s", "value": True})


def test_stale_settings_are_dropped_on_load(tmp_path: Path, assets: Path) -> None:
    StateStore(tmp_path / "state.json").save(Overrides(settings={"gone.setting": 3.0, "lightning.min_interval_s": 10.0}))
    p = program(tmp_path, assets)
    assert p.overrides.settings == {"lightning.min_interval_s": 10.0}
    assert p.lightning.intervals_s == (200.0, 10.0)


def test_lightning_reschedules_when_its_intervals_change(clock: FakeClock) -> None:
    lightning, _, _ = make_lightning(clock, LightningConfig(mean_interval_s=1200, min_interval_s=300))
    assert lightning.time_to_next() >= 300
    lightning.set_intervals(10.0, 5.0)
    assert 5.0 <= lightning.time_to_next() < 300
    with pytest.raises(ValueError):
        lightning.set_intervals(0.0, 5.0)


@pytest.mark.asyncio
async def test_lightning_loop_honours_a_shorter_wait(clock: FakeClock) -> None:
    lightning, _, engine = make_lightning(clock, LightningConfig(mean_interval_s=1000, min_interval_s=1000, thunder_delay_s=(0.05, 0.1)))
    task = asyncio.create_task(lightning.run())
    await asyncio.sleep(0.05)
    lightning.set_intervals(0.001, 0.001)  # due almost at once (the mean is floored at a second), well inside the old sleep
    clock.advance(5.0)
    await asyncio.sleep(1.3)  # the loop naps a second at a time
    task.cancel()
    assert engine._overlays or lightning.last_origin is not None  # it struck
