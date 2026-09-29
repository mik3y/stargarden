"""Console overrides that persist: the file, and the program applying it."""

import json
import logging
from pathlib import Path

import pytest

from stargarden.app import Stargarden
from stargarden.audio import Layer
from stargarden.conductor import State
from stargarden.console import ActionError, Console, install_log_buffer
from stargarden.lighting.themes import AMBIENT_THEMES, SHOW_THEMES
from stargarden.manifest import load_manifest
from stargarden.state import Overrides, StateStore
from test_app import make_config


def test_store_round_trips_only_what_changed(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "deep" / "state.json")
    assert store.load() == Overrides()  # no file yet
    store.save(Overrides({"bed": 0.5}, 0.7, {"orbit"}))
    assert json.loads(store.path.read_text()) == {"levels": {"bed": 0.5}, "peak": 0.7, "disabled_themes": ["orbit"]}
    assert store.load() == Overrides({"bed": 0.5}, 0.7, {"orbit"})
    assert not list(store.path.parent.glob("*.tmp"))  # written via rename
    store.save(Overrides())  # nothing overridden: no file
    assert not store.path.exists()


def test_store_ignores_a_broken_file(tmp_path: Path, caplog) -> None:
    store = StateStore(tmp_path / "state.json")
    for bad in ("{not json", '{"levels": "loud"}', '{"peak": true}', '{"disabled_themes": "orbit"}', "[]"):
        store.path.write_text(bad)
        with caplog.at_level(logging.WARNING):
            assert store.load() == Overrides()
        assert "ignoring" in caplog.text
        caplog.clear()


def program(tmp_path: Path, assets: Path) -> Stargarden:
    config = make_config(tmp_path, assets)
    p = Stargarden(config, load_manifest(config.assets_root), seed=1)
    p.conductor.set_night(True)
    return p


def test_console_changes_persist_and_apply_on_the_next_launch(tmp_path: Path, assets: Path) -> None:
    p = program(tmp_path, assets)
    console = Console(p, install_log_buffer("INFO"))
    console.act("set_level", {"name": "bed", "value": 0.25})
    console.act("set_level", {"name": "peak", "value": 0.6})
    ambient = [n for n in AMBIENT_THEMES]
    console.act("set_theme_enabled", {"name": ambient[0], "enabled": False})
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved == {"levels": {"bed": 0.25}, "peak": 0.6, "disabled_themes": [ambient[0]]}

    again = program(tmp_path, assets)  # the same config file, a fresh run
    assert again.audio.level(Layer.BED) == pytest.approx(0.25) and again.audio.level(Layer.MUSIC) == pytest.approx(0.9)
    assert again.lighting.peak == pytest.approx(0.6)
    assert again.lighting.theme.name != ambient[0]  # never picked at start
    programs = {s.name: s for s in Console(again, install_log_buffer("INFO")).status().programs}
    assert programs[ambient[0]].enabled is False and all(programs[n].enabled for n in list(SHOW_THEMES) + ambient[1:])
    assert sum(s.playing for s in programs.values()) == 1


def test_at_least_one_program_per_pool_stays_enabled(tmp_path: Path, assets: Path) -> None:
    p = program(tmp_path, assets)
    console = Console(p, install_log_buffer("INFO"))
    show = list(SHOW_THEMES)
    for name in show[1:]:
        console.act("set_theme_enabled", {"name": name, "enabled": False})
    with pytest.raises(ActionError, match="at least one show program"):
        console.act("set_theme_enabled", {"name": show[0], "enabled": False})
    with pytest.raises(ActionError, match="unknown program"):
        console.act("set_theme_enabled", {"name": "disco", "enabled": False})
    with pytest.raises(ActionError):
        console.act("set_theme_enabled", {"name": show[0], "enabled": "no"})


def test_disabling_the_playing_ambient_program_moves_on(tmp_path: Path, assets: Path) -> None:
    p = program(tmp_path, assets)
    console = Console(p, install_log_buffer("INFO"))
    p.conductor.force(State.AMBIENT)
    playing = p.lighting.theme.name
    console.act("set_theme_enabled", {"name": playing, "enabled": False})
    assert p.lighting.theme.name != playing and p.ambient_theme is p.lighting.theme
    assert p.ambient_theme.name in p.enabled_themes(AMBIENT_THEMES)
    # `next_theme` still walks every program, disabled ones included, for a look
    names = list(AMBIENT_THEMES)
    assert [console.act("next_theme") for _ in names] == [
        names[(names.index(p.ambient_theme.name) + k) % len(names)] for k in range(1, len(names) + 1)
    ]


def test_play_by_name_and_reset(tmp_path: Path, assets: Path) -> None:
    p = program(tmp_path, assets)
    console = Console(p, install_log_buffer("INFO"))
    assert console.act("set_theme", {"name": "orbit"}) == "orbit" and p.lighting.theme.name == "orbit" and p.show_theme.name == "orbit"
    with pytest.raises(ActionError, match="unknown program"):
        console.act("set_theme", {"name": "disco"})
    console.act("set_level", {"name": "music", "value": 0.1})
    console.act("set_theme_enabled", {"name": "green-tide", "enabled": False})
    assert (tmp_path / "state.json").exists()
    console.act("reset_defaults")
    assert not (tmp_path / "state.json").exists()
    assert p.audio.level(Layer.MUSIC) == pytest.approx(0.9) and p.lighting.peak == 1.0
    assert all(s.enabled for s in console.status().programs)
