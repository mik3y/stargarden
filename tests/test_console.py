"""The control surface both consoles share: snapshots and named actions."""

import logging
from dataclasses import asdict

import pytest

from stargarden.app import Stargarden
from stargarden.audio import Layer
from stargarden.conductor import State
from stargarden.config import SensorRole
from stargarden.console import LEVELS, ActionError, Console, LogBuffer, UnknownAction, install_log_buffer, record_to_dict
from stargarden.manifest import load_manifest
from test_app import make_config


@pytest.fixture
def console(tmp_path, assets) -> Console:
    config = make_config(tmp_path, assets)
    program = Stargarden(config, load_manifest(config.assets_root), seed=1)
    program.conductor.set_night(True)
    return Console(program, install_log_buffer("INFO"))


def test_status_is_plain_data(console: Console) -> None:
    status = asdict(console.status())
    assert status["state"] == "ambient" and status["forced"] is None
    assert status["night"] is True and status["night_override"] is None
    assert status["next_transition"] is None  # the schedule is off in the test config
    assert set(status["motion_ago_s"]) == {"platform", "walkway"}
    assert list(status["levels"]) == list(LEVELS) and status["levels"]["peak"] == 1.0
    assert status["driver"] == "console" and status["debug"] is False


def test_fixture_preview_rows(console: Console) -> None:
    (preview,) = console.fixtures()
    assert preview.name == "a"
    assert len(preview.rows) == 1 and len(preview.rows[0]) == 1  # the generic wash is one color cell
    assert preview.rows[0][0].rgb == (0, 0, 0)  # nothing rendered yet: blacked out
    assert asdict(preview)["rows"][0][0] == {"name": "cell", "rgb": (0, 0, 0), "strobe": False}
    assert preview.whites == ()  # `dim_rgbw` has a white emitter on the cell, not a white cell of its own


def test_fixture_preview_of_a_bar(tmp_path, assets) -> None:
    config = make_config(tmp_path, assets)
    config.path.write_text(config.path.read_text().replace('type = "generic"\nmode = "dim_rgbw"', 'type = "jolt_bar_fx2"\nmode = "38ch"'))
    from stargarden.config import load_config

    program = Stargarden(load_config(config.path), load_manifest(config.assets_root), seed=1)
    (preview,) = Console(program, LogBuffer()).fixtures()
    assert [len(row) for row in preview.rows] == [4, 4]  # two rows of four RGB columns
    assert len({c.name for row in preview.rows for c in row}) == 8  # every cell keyed by its own name
    assert len(preview.whites) == 4 and preview.whites[0].rgb == (0, 0, 0)


def test_actions_by_name(console: Console) -> None:
    p = console.program
    console.act("motion", {"role": "platform"})
    assert p.conductor.state is State.PRESENCE
    console.act("force", {"state": "off"})  # (forcing a show needs the event loop; see test_web)
    assert p.conductor.forced is State.OFF and p.conductor.state is State.OFF
    console.act("release")
    assert p.conductor.forced is None
    assert p.conductor.state is State.PRESENCE
    assert console.act("toggle_night") is False and p.night_override is False and p.conductor.state is State.OFF
    console.act("set_night", {"night": None})
    assert p.night_override is None
    assert console.act("set_level", {"name": "bed", "value": 0.5}) == 0.5
    assert p.audio.level(Layer.BED) == 0.5
    assert console.act("set_level", {"name": "peak", "value": 7}) == 1.0  # clamped
    assert console.act("nudge_level", {"name": "peak", "delta": -0.05}) == pytest.approx(0.95)
    assert console.act("set_debug", {"debug": True}) is True and logging.getLogger().level == logging.DEBUG
    assert console.act("toggle_debug") is False
    assert console.act("discrete") is True
    console.act("lightning")
    assert p.lighting._overlays


def test_bad_actions_are_errors(console: Console) -> None:
    with pytest.raises(UnknownAction):
        console.act("shutdown")
    with pytest.raises(UnknownAction):
        console.act("status")  # a snapshot, not an action
    with pytest.raises(ActionError, match="force"):
        console.act("force", {"state": "party"})
    with pytest.raises(ActionError):
        console.act("force", {"nope": 1})
    with pytest.raises(ActionError, match="unknown level"):
        console.act("set_level", {"name": "reverb", "value": 0.5})
    with pytest.raises(ActionError):
        console.act("set_level", {"name": "bed", "value": "loud"})
    with pytest.raises(ActionError):
        console.act("set_night", {"night": "yes"})
    assert console.program.conductor.forced is None


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


def test_install_log_buffer_headless_adds_stderr() -> None:
    buffer = install_log_buffer("INFO", stderr=True)
    handlers = logging.getLogger().handlers
    assert handlers[0] is buffer and isinstance(handlers[1], logging.StreamHandler)
    install_log_buffer("INFO")
    assert len(logging.getLogger().handlers) == 1


def test_motion_roles_are_validated(console: Console) -> None:
    console.motion(SensorRole.WALKWAY)  # enums pass through too
    assert console.program.occupancy.seconds_since(SensorRole.WALKWAY) is not None
