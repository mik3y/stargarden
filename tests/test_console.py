"""The console's control surface: snapshots and named actions."""

import logging
from dataclasses import asdict

import pytest

from stargarden.app import Stargarden
from stargarden.config import Config, load_config
from stargarden.console import PALETTE_STEPS, ActionError, Console, LogBuffer, UnknownAction, install_log_buffer, record_to_dict


@pytest.fixture
def console(config: Config, clock) -> Console:
    return Console(Stargarden(config, clock), install_log_buffer("INFO"))


def test_status_is_plain_data(console: Console) -> None:
    status = asdict(console.status())
    assert status["site"] == "Stargarden" and status["on"] is True and status["driver"] == "console"
    assert (status["position"], status["shown"], status["direction"], status["paused"]) == (0.0, 0.0, "darkening", False)
    assert (status["leg_s"], status["leg_remaining_s"], status["peak"], status["dusk_level"]) == (100.0, 100.0, 1.0, 0.4)
    assert status["debug"] is False and status["check"] is False
    palette = status["palette"]
    assert len(palette) == PALETTE_STEPS and palette[0] == (255, 107, 5)  # orange at full
    assert palette[-1] == (33, 0, 80)  # purple at the dusk level


def test_fixture_preview_rows(console: Console) -> None:
    (preview,) = console.fixtures()
    assert preview.name == "a"
    assert len(preview.rows) == 1 and len(preview.rows[0]) == 1  # the generic wash is one color cell
    assert preview.rows[0][0].rgb == (0, 0, 0)  # nothing rendered yet: blacked out
    assert asdict(preview)["rows"][0][0] == {"name": "cell", "rgb": (0, 0, 0), "strobe": False}
    assert preview.whites == ()  # `dim_rgbw` has a white emitter on the cell, not a white cell of its own


def test_fixture_preview_of_a_bar(config: Config) -> None:
    config.path.write_text(config.path.read_text().replace('type = "generic"\nmode = "dim_rgbw"', 'type = "jolt_bar_fx2"\nmode = "38ch"'))
    (preview,) = Console(Stargarden(load_config(config.path)), LogBuffer()).fixtures()
    assert [len(row) for row in preview.rows] == [4, 4]  # two rows of four RGB columns
    assert len({c.name for row in preview.rows for c in row}) == 8  # every cell keyed by its own name
    assert len(preview.whites) == 4 and preview.whites[0].rgb == (0, 0, 0)


def test_levels_and_debug(console: Console) -> None:
    assert console.act("set_peak", {"value": 7}) == 1.0  # clamped
    assert console.act("set_peak", {"value": 0.25}) == 0.25 and console.program.lighting.peak == 0.25
    assert console.act("set_dusk_level", {"value": 0}) == pytest.approx(0.05)  # never black
    assert console.act("set_debug", {"debug": True}) is True and logging.getLogger().level == logging.DEBUG
    assert console.act("toggle_debug") is False


def test_bad_actions_are_errors(console: Console) -> None:
    with pytest.raises(UnknownAction):
        console.act("shutdown")
    with pytest.raises(UnknownAction):
        console.act("status")  # a snapshot, not an action
    with pytest.raises(ActionError, match="set_peak"):
        console.act("set_peak", {"value": "bright"})
    with pytest.raises(ActionError):
        console.act("set_peak", {"nope": 1})
    with pytest.raises(ActionError):
        console.act("set_paused", {"paused": 1})
    assert console.program.sunset.paused is False


def test_log_buffer_is_shared_by_sequence() -> None:
    buffer = LogBuffer(maxlen=3)
    logger = logging.getLogger("stargarden.test")
    logger.propagate = False
    logger.addHandler(buffer)
    logger.setLevel(logging.INFO)
    try:
        logger.info("one")
        logger.info("two %s", "b")
        records, seq = buffer.since(0)
        assert [r.getMessage() for _, r in records] == ["one", "two b"] and seq == 2
        assert buffer.since(seq) == ([], 2)  # a second reader keeps its own place
        logger.info("three")
        logger.info("four")
        records, seq = buffer.since(1)
        assert [(s, r.getMessage()) for s, r in records] == [(1, "two b"), (2, "three"), (3, "four")]  # "one" fell off the ring
        line = record_to_dict(*records[0])
        assert (line["seq"], line["level"], line["name"], line["msg"], line["exc"]) == (1, "INFO", "test", "two b", None)
    finally:
        logger.removeHandler(buffer)


def test_install_log_buffer_also_logs_to_stderr() -> None:
    buffer = install_log_buffer("INFO")
    handlers = logging.getLogger().handlers
    assert handlers[0] is buffer and isinstance(handlers[1], logging.StreamHandler) and len(handlers) == 2
