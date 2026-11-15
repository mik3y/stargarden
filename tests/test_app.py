"""The runtime: console changes take effect, persist, and come back on the next launch."""

import asyncio
import json

import pytest

from stargarden.app import Stargarden
from stargarden.config import Config
from stargarden.console import ActionError, Console, install_log_buffer


def lit(program: Stargarden) -> float:
    """The first fixture's brightness, rendered now."""
    return program.lighting.frame(program.lighting._clock())[0]["cell"].intensity


@pytest.mark.asyncio
async def test_lights_come_up_and_switch_off(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("stargarden.app.FADE_S", 0.05)
    program = Stargarden(config)
    console = Console(program, install_log_buffer("INFO"))

    async def drive() -> None:
        await asyncio.sleep(0.15)
        assert console.status().on and lit(program) == pytest.approx(1.0, abs=0.01)  # up by itself at the orange end
        assert max(console.fixtures()[0].rows[0][0].rgb) == 255
        assert console.act("set_on", {"on": False}) is False
        await asyncio.sleep(0.15)
        assert lit(program) == 0.0 and console.status().master == 0.0
        assert console.act("toggle_on") is True
        await asyncio.sleep(0.15)
        assert lit(program) > 0.9

    await program.run(foreground=drive())


def test_changes_persist_and_apply_on_the_next_launch(config: Config, clock) -> None:
    program = Stargarden(config, clock)
    console = Console(program, install_log_buffer("INFO"))
    state = config.state.path
    assert not state.exists()
    assert console.act("set_leg", {"seconds": 1800}) == 1800.0
    assert console.act("set_peak", {"value": 0.6}) == 0.6
    assert console.act("set_dusk_level", {"value": 0.2}) == 0.2
    assert console.act("set_position", {"position": 0.75}) == 0.75
    assert json.loads(state.read_text()) == {"peak": 0.6, "leg_s": 1800.0, "dusk_level": 0.2, "hold": 0.75}

    again = Stargarden(config, clock)  # the same config file, a fresh run
    status = Console(again, install_log_buffer("INFO")).status()
    assert (status.leg_s, status.peak, status.dusk_level) == (1800.0, 0.6, 0.2)
    assert status.paused and status.position == 0.75 and status.shown == 0.75  # held where it was, shown at once

    console.act("set_paused", {"paused": False})
    assert "hold" not in json.loads(state.read_text())  # a running sunset starts from orange next time
    console.act("set_leg", {"seconds": config.sunset.leg_s})
    assert "leg_s" not in json.loads(state.read_text())  # back at the default: nothing to store
    console.act("reset_defaults")
    assert not state.exists()
    assert (program.sunset.leg_s, program.sunset.dusk_level, program.lighting.peak) == (100.0, 0.4, 1.0)


def test_program_tempo_and_spots_persist(config: Config, clock) -> None:
    program = Stargarden(config, clock)
    console = Console(program, install_log_buffer("INFO"))
    status = console.status()
    assert status.program == "sunset" and status.programs == ["sunset", "blocks", "chase", "checker", "pulse"]
    assert (status.tempo, status.spots, status.spot_level, status.spot_color) == (100.0, False, 1.0, "white")
    assert console.act("set_program", {"name": "checker"}) == "checker" and console.status().program == "checker"
    assert console.act("set_tempo", {"bpm": 120}) == 120.0
    assert console.act("set_spot_level", {"value": 0.4}) == 0.4
    assert console.act("set_spot_color", {"color": "match"}) == "match"
    saved = json.loads(config.state.path.read_text())
    assert saved == {"tempo": 120.0, "spot_level": 0.4, "program": "checker", "spot_color": "match"}

    again = Console(Stargarden(config, clock), install_log_buffer("INFO")).status()
    assert (again.program, again.tempo, again.spot_level, again.spot_color) == ("checker", 120.0, 0.4, "match")

    for action, params in (("set_program", {"name": "disco"}), ("set_tempo", {"bpm": 5}), ("set_spot_color", {"color": "green"})):
        with pytest.raises(ActionError, match=action):
            console.act(action, params)
    console.act("set_program", {"name": "sunset"})
    assert "program" not in json.loads(config.state.path.read_text())
    console.act("set_program", {"name": "pulse"})
    console.act("reset_defaults")
    status = console.status()
    assert (status.program, status.tempo, status.spot_level, status.spot_color) == ("sunset", 100.0, 1.0, "white")
    assert not config.state.path.exists()


def test_a_saved_program_since_removed_is_dropped(config: Config, clock) -> None:
    config.state.path.write_text(json.dumps({"program": "lasers", "peak": 0.5}))
    program = Stargarden(config, clock)
    assert program.lighting.program is program.sunset and program.lighting.peak == 1.0


def test_a_saved_setting_that_no_longer_fits_is_dropped(config: Config, clock) -> None:
    config.state.path.write_text(json.dumps({"leg_s": 1, "peak": 0.5}))
    program = Stargarden(config, clock)
    assert program.sunset.leg_s == 100.0 and program.lighting.peak == 1.0


def test_manual_moves_hold_and_resume_runs_on(config: Config, clock) -> None:
    program = Stargarden(config, clock)
    console = Console(program, install_log_buffer("INFO"))
    clock.advance(10)
    assert console.act("nudge") == pytest.approx(0.15) and console.status().paused  # one step darker, and held there
    assert console.act("nudge", {"steps": -2}) == pytest.approx(0.05)
    clock.advance(1000)
    assert console.status().position == pytest.approx(0.05)
    assert console.act("toggle_paused") is False
    clock.advance(10)
    assert console.status().position == pytest.approx(0.15) and console.status().direction == "darkening"
    assert console.act("toggle_paused") is True
    console.act("restart")
    status = console.status()
    assert status.position == 0.0 and not status.paused and status.leg_remaining_s == 100.0
    with pytest.raises(ActionError, match="set_leg"):
        console.act("set_leg", {"seconds": 1})
    with pytest.raises(ActionError):
        console.act("set_position", {"position": "dusk"})
    with pytest.raises(ActionError):
        console.act("set_on", {"on": "yes"})
