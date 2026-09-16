"""Drive the console with Textual's pilot: keys reach the program."""

import logging
from dataclasses import replace

import pytest

from stargarden.app import Stargarden
from stargarden.audio import Layer
from stargarden.conductor import State
from stargarden.manifest import load_manifest
from stargarden.tui import StargardenApp, install_log_buffer
from stargarden.tui.app import LogPane, format_record, swatch_rgb
from test_app import make_config


@pytest.mark.asyncio
async def test_console_keys_drive_program(tmp_path, assets) -> None:
    config = make_config(tmp_path, assets)
    # keys, not timers, drive this test: keep the show and the vacancy timeout out of the way
    config = replace(config, timers=replace(config.timers, show_delay_s=30), presence=replace(config.presence, vacancy_timeout_s=30))
    program = Stargarden(config, load_manifest(config.assets_root), seed=1)
    app = StargardenApp(program, install_log_buffer("INFO"))

    async def drive() -> None:
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            assert program.conductor.state is State.AMBIENT
            # the layout must fit the screen: a visible log pane and nothing scrolled off the top
            assert app.query_one(LogPane).size.height > 5
            assert app.screen.scroll_y == 0 and app.screen.virtual_size.height <= app.size.height
            await pilot.resize_terminal(110, 38)  # Textual schedules a resize check with set_timer; it must not crash
            await pilot.pause(0.3)
            assert app._exception is None
            await pilot.press("m")
            assert program.conductor.state is State.PRESENCE
            await pilot.press("2")
            assert program.conductor.forced is State.PRESENCE
            await pilot.press("n")  # day override: the forced state still pins
            assert not program.conductor.night and program.conductor.state is State.PRESENCE
            await pilot.press("r")
            assert program.conductor.forced is None and program.conductor.state is State.OFF
            await pilot.press("tab", "right_square_bracket")
            assert program.audio.level(Layer.DISCRETES) == pytest.approx(0.75)
            await pilot.press("tab", "tab", "left_square_bracket")  # past music to the lighting peak
            assert program.lighting.peak == pytest.approx(0.95)
            await pilot.press("tab", "left_square_bracket")  # wraps back to the bed
            assert program.audio.level(Layer.BED) == pytest.approx(0.75) and program.lighting.peak == pytest.approx(0.95)
            await pilot.press("l", "s")
            await pilot.pause(0.4)
            assert len(app.query_one(LogPane).lines) > 0
            await pilot.press("d")
            assert logging.getLogger().level == logging.DEBUG
            await pilot.press("d")
            assert logging.getLogger().level == logging.INFO
            await pilot.press("ctrl+c")  # quits immediately, no "press ctrl+q" hint
            assert app._exit

    await program.run(foreground=drive())


def test_swatches_preview_at_full_peak() -> None:
    assert swatch_rgb((1.0, 0.5, 0.0), 0.8, 1.0) == (204, 102, 0)
    assert swatch_rgb((1.0, 0.5, 0.0), 0.08, 0.1) == (204, 102, 0)  # peak 0.1 dims the wire, not the preview
    assert swatch_rgb((1.0, 0.5, 0.0), 1.0, 0.1) == (255, 128, 0)  # a lightning flash (exempt from the peak) clamps
    assert swatch_rgb((1.0, 0.5, 0.0), 0.0, 0.0) == (0, 0, 0)


def test_format_record_columns_and_traceback() -> None:
    record = logging.LogRecord("stargarden.audio.engine", logging.WARNING, __file__, 1, "bed %s", ("creek.wav",), None)
    line = format_record(record).plain
    assert line.endswith("WARN  audio.engine     bed creek.wav")
    assert line[2] == ":" and line[8] == "."  # HH:MM:SS.mmm
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("stargarden.app", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    text = format_record(record).plain
    assert "ERROR app" in text and "ValueError: boom" in text
