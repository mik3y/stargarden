"""Drive the console with Textual's pilot: keys reach the program."""

import pytest
from textual.widgets import RichLog

from stargarden.app import Stargarden
from stargarden.audio import Layer
from stargarden.conductor import State
from stargarden.manifest import load_manifest
from stargarden.tui import StargardenApp, install_log_buffer
from test_app import make_config


@pytest.mark.asyncio
async def test_console_keys_drive_program(tmp_path, assets) -> None:
    config = make_config(tmp_path, assets)
    program = Stargarden(config, load_manifest(config.assets_root), seed=1)
    app = StargardenApp(program, install_log_buffer("INFO"))

    async def drive() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            assert program.conductor.state is State.AMBIENT
            await pilot.press("m")
            assert program.conductor.state is State.PRESENCE
            await pilot.press("3")
            assert program.conductor.state is State.SHOW and program.conductor.forced is State.SHOW
            await pilot.press("n")  # day override: forced show still pins the state
            assert not program.conductor.night and program.conductor.state is State.SHOW
            await pilot.press("r")
            assert program.conductor.state is State.OFF
            await pilot.press("tab", "right_square_bracket")
            assert program.audio.level(Layer.DISCRETES) == pytest.approx(0.75)
            await pilot.press("l", "s")
            await pilot.pause(0.4)
            assert len(app.query_one("#log", RichLog).lines) > 0

    await program.run(foreground=drive())
