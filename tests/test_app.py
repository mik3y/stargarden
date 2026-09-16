"""End-to-end: the runtime wires up in simulation and a show plays through."""

import asyncio
from pathlib import Path

import pytest

from stargarden.app import Stargarden
from stargarden.conductor import State
from stargarden.config import Config, SensorRole, load_config
from stargarden.manifest import load_manifest


def make_config(tmp_path: Path, assets: Path) -> Config:
    path = tmp_path / "cfg.toml"
    path.write_text(
        f"""
[schedule]
enabled = false
[timers]
show_delay_s = 0.3
show_repeat_delay_s = 0.3
lights_out_s = 0.1
[audio]
backend = "null"
mode = "stereo"
blocksize = 256
duck_fade_s = 0.1
bed_crossfade_s = 0.1
[presence]
vacancy_timeout_s = 0.8
[lighting]
driver = "console"
fps = 60
[[lighting.fixtures]]
name = "a"
type = "generic"
mode = "dim_rgbw"
address = 1
[assets]
root = "{assets}"
"""
    )
    return load_config(path)


@pytest.mark.asyncio
async def test_full_visit(tmp_path: Path, assets: Path) -> None:
    config = make_config(tmp_path, assets)
    program = Stargarden(config, load_manifest(config.assets_root), seed=1)
    states: list[State] = []
    program.conductor.add_listener(lambda old, new: states.append(new))

    async def scenario() -> None:
        await asyncio.sleep(0.3)
        assert program.conductor.state is State.AMBIENT
        assert program.audio.ambient_running
        program.simulate_motion(SensorRole.PLATFORM)
        assert program.conductor.state is State.PRESENCE
        await asyncio.sleep(0.6)
        assert program.conductor.state is State.SHOW
        # the track is ~0.1s at 48k; wait for it to finish, then vacancy to lapse
        for _ in range(60):
            await asyncio.sleep(0.05)
            if program.conductor.state is State.AMBIENT:
                break
        assert program.audio.current_music is None
        assert states[:3] == [State.AMBIENT, State.PRESENCE, State.SHOW]
        assert State.PRESENCE in states[3:] or states[3] is State.AMBIENT
        assert program.conductor.state is State.AMBIENT
        await asyncio.sleep(0.2)
        assert program.lighting.driver.frame[0] > 0  # dimmer coming back up
        program.shutdown()

    await program.run(foreground=scenario())
