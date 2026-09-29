"""Show tracks from the console: the rotation, the queue for the next show, and playing one now."""

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from conftest import write_wav
from stargarden.app import Stargarden
from stargarden.conductor import State
from stargarden.console import ActionError, Console, install_log_buffer
from stargarden.manifest import ManifestError, load_manifest
from stargarden.state import Overrides, StateStore
from test_app import make_config


def assets_with_tracks(tmp_path: Path, seconds: float = 0.1) -> Path:
    root = tmp_path / "assets"
    n = int(48000 * seconds)
    ramp = np.linspace(-0.5, 0.5, n, dtype=np.float32)
    write_wav(root / "beds" / "bed.wav", np.stack([ramp[:4800], -ramp[:4800]], axis=1), 48000)
    for name in ("a", "b", "c"):
        write_wav(root / "music" / f"{name}.wav", np.stack([ramp, ramp], axis=1), 48000)
    (root / "manifest.toml").write_text(
        """
[[beds]]
file = "beds/bed.wav"
[[music]]
file = "music/a.wav"
title = "A"
bpm = 90
[[music]]
file = "music/b.wav"
title = "B"
theme = "orbit"
[[music]]
file = "music/c.wav"
title = "C"
"""
    )
    return root


def program(tmp_path: Path, seconds: float = 0.1) -> Stargarden:
    config = make_config(tmp_path, assets_with_tracks(tmp_path, seconds))
    p = Stargarden(config, load_manifest(config.assets_root), seed=1)
    p.conductor.set_night(True)
    return p


def test_manifest_ids_and_enabled_picks(tmp_path: Path) -> None:
    m = load_manifest(assets_with_tracks(tmp_path))
    assert [t.id for t in m.music] == ["music/a.wav", "music/b.wav", "music/c.wav"]
    assert m.track("music/b.wav").title == "B"
    with pytest.raises(KeyError):
        m.track("music/zzz.wav")
    import random

    rng = random.Random(3)
    picks = {m.pick_music(rng, enabled=["music/c.wav"]).id for _ in range(10)}
    assert picks == {"music/c.wav"}
    picks = {m.pick_music(rng, avoid=m.music[2], enabled=["music/c.wav"]).id for _ in range(10)}
    assert picks == {"music/c.wav"}  # the only enabled one wins over `avoid`
    picks = {m.pick_music(rng, enabled=["nope"]).id for _ in range(30)}
    assert picks == {t.id for t in m.music}  # nothing enabled: the whole list

    (tmp_path / "assets" / "manifest.toml").write_text('[[music]]\nfile = "music/a.wav"\n[[music]]\nfile = "music/a.wav"\n')
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "assets")


def test_disabled_tracks_persist(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.json")
    store.save(Overrides(disabled_tracks={"music/b.wav"}))
    assert json.loads(store.path.read_text()) == {"disabled_tracks": ["music/b.wav"]}
    assert store.load() == Overrides(disabled_tracks={"music/b.wav"})
    store.path.write_text('{"disabled_tracks": "music/b.wav"}')
    assert store.load() == Overrides()

    p = program(tmp_path)
    console = Console(p, install_log_buffer("INFO"))
    console.act("set_track_enabled", {"id": "music/b.wav", "enabled": False})
    console.act("set_track_enabled", {"id": "music/c.wav", "enabled": False})
    with pytest.raises(ActionError, match="at least one"):
        console.act("set_track_enabled", {"id": "music/a.wav", "enabled": False})
    with pytest.raises(ActionError, match="unknown track"):
        console.act("set_track_enabled", {"id": "music/zzz.wav", "enabled": False})
    with pytest.raises(ActionError):
        console.act("set_track_enabled", {"id": "music/a.wav", "enabled": "no"})
    assert json.loads((tmp_path / "state.json").read_text())["disabled_tracks"] == ["music/b.wav", "music/c.wav"]

    again = program(tmp_path)
    assert again.enabled_tracks() == ["music/a.wav"]
    tracks = {t.id: t for t in Console(again, install_log_buffer("INFO")).status().tracks}
    assert [t.enabled for t in tracks.values()] == [True, False, False]
    assert tracks["music/a.wav"].bpm == 90 and tracks["music/b.wav"].theme == "orbit" and tracks["music/c.wav"].bpm is None
    assert not any(t.playing or t.next for t in tracks.values())
    again.reset_overrides()
    assert again.enabled_tracks() == ["music/a.wav", "music/b.wav", "music/c.wav"]


def test_queue_then_show(tmp_path: Path) -> None:
    p = program(tmp_path)
    console = Console(p, install_log_buffer("INFO"))
    assert console.act("queue_track", {"id": "music/c.wav"}) == "music/c.wav"
    assert [t.id for t in console.status().tracks if t.next] == ["music/c.wav"]
    assert console.act("queue_track", {"id": None}) is None
    assert p.next_music is None
    with pytest.raises(ActionError, match="unknown track"):
        console.act("queue_track", {"id": "music/zzz.wav"})
    with pytest.raises(ActionError):
        console.act("queue_track", {"id": 7})


@pytest.mark.asyncio
async def test_queued_track_plays_next_and_play_now_starts_over(tmp_path: Path) -> None:
    p = program(tmp_path, seconds=3.0)
    console = Console(p, install_log_buffer("INFO"))
    for m in p.manifest.music:  # the rotation would only ever pick A
        if m.id != "music/a.wav":
            p.set_track_enabled(m.id, False)

    async def scenario() -> None:
        await asyncio.sleep(0.3)
        assert p.conductor.state is State.AMBIENT
        console.act("queue_track", {"id": "music/c.wav"})
        p.conductor.force(State.SHOW)
        await asyncio.sleep(1.5)  # lights out, then the track starts
        assert p.audio.current_music is not None and p.audio.current_music.id == "music/c.wav"  # queued beats the rotation
        assert p.next_music is None
        tracks = {t.id: t for t in console.status().tracks}
        assert tracks["music/c.wav"].playing and not tracks["music/c.wav"].next

        assert console.act("play_track", {"id": "music/b.wav"}) == "music/b.wav"  # mid-show: start over
        assert p.conductor.state is State.SHOW and p.audio.current_music is None  # the old track fades with the lights
        await asyncio.sleep(1.5)
        assert p.audio.current_music is not None and p.audio.current_music.id == "music/b.wav"
        assert p.lighting.theme.name == "orbit"

        p.conductor.force(State.AMBIENT)
        await asyncio.sleep(0.2)
        assert p.audio.current_music is None
        console.act("play_track", {"id": "music/a.wav"})  # not in a show: enter one, pinned until the track ends
        assert p.conductor.state is State.SHOW and p.conductor.forced is State.SHOW
        await asyncio.sleep(1.5)
        assert p.audio.current_music is not None and p.audio.current_music.id == "music/a.wav"
        assert p.lighting.tempo == 90
        p.shutdown()

    await p.run(foreground=scenario())
