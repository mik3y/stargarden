"""The overrides file."""

import json
import logging
from pathlib import Path

from stargarden.state import Overrides, StateStore


def test_store_round_trips_only_what_changed(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "deep" / "state.json")
    assert store.load() == Overrides()  # no file yet
    store.save(Overrides(peak=0.7, hold=0.25))
    assert json.loads(store.path.read_text()) == {"peak": 0.7, "hold": 0.25}
    assert store.load() == Overrides(peak=0.7, hold=0.25)
    assert not list(store.path.parent.glob("*.tmp"))  # written via rename
    store.save(Overrides())  # nothing overridden: no file
    assert not store.path.exists()


def test_store_ignores_a_broken_file_and_names_since_dropped(tmp_path: Path, caplog) -> None:
    store = StateStore(tmp_path / "state.json")
    for bad in ("{not json", '{"leg_s": "long"}', '{"peak": true}', "[]"):
        store.path.write_text(bad)
        with caplog.at_level(logging.WARNING):
            assert store.load() == Overrides()
        assert "ignoring" in caplog.text
        caplog.clear()
    store.path.write_text('{"peak": 0.5, "levels": {"bed": 0.5}, "disabled_themes": ["orbit"]}')  # a file from the forest
    assert store.load() == Overrides(peak=0.5)
