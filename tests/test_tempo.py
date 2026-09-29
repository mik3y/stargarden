"""Tempo detection, the cache that outlives deploys, and the background analyzer."""

import json
import os
import threading
from pathlib import Path

import numpy as np
import pytest

from conftest import write_wav
from stargarden.audio.tempo import TempoAnalyzer, TempoCache, detect_bpm, detect_file_bpm, fold_bpm
from stargarden.manifest import ManifestError, load_manifest

RATE = 11025


def clicks(bpm: float, seconds: float = 40.0, rate: int = RATE, seed: int = 0) -> np.ndarray:
    """Noise bursts on the beat over a quiet noise floor, mono float32."""
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.02, int(seconds * rate)).astype(np.float32)
    burst = (rng.normal(0, 1, 500) * np.exp(-np.arange(500) / 80)).astype(np.float32) * 0.6
    t = 0.0
    while t < seconds:
        i = int(t * rate)
        x[i : i + 500] += burst[: len(x[i : i + 500])]
        t += 60.0 / bpm
    return x


def test_fold_into_one_octave() -> None:
    assert fold_bpm(100) == 100
    assert fold_bpm(160) == 80
    assert fold_bpm(280) == 70
    assert fold_bpm(60) == 120
    assert fold_bpm(140) == 70  # the top of the range is the bottom's octave
    assert fold_bpm(30) == 120
    assert fold_bpm(50, 60, 120) == 100
    with pytest.raises(ValueError):
        fold_bpm(0)


@pytest.mark.parametrize("bpm", [72, 100, 118, 138])
def test_detects_clicks_in_range(bpm: float) -> None:
    got = detect_bpm(clicks(bpm), RATE)
    assert got is not None and abs(got - bpm) < 1.0
    assert type(got) is float


@pytest.mark.parametrize(("bpm", "folded"), [(160, 80), (60, 120), (50, 100)])
def test_folds_clicks_outside_the_range(bpm: float, folded: float) -> None:
    got = detect_bpm(clicks(bpm), RATE)
    assert got is not None and abs(got - folded) < 1.0


def test_nothing_to_measure() -> None:
    assert detect_bpm(np.zeros(RATE * 20, np.float32), RATE) is None  # silence
    assert detect_bpm(clicks(100, seconds=3), RATE) is None  # too short
    assert detect_bpm(np.zeros(10, np.float32), RATE) is None


def test_detects_from_a_stereo_file(tmp_path: Path) -> None:
    mono = clicks(100, rate=44100)
    path = write_wav(tmp_path / "song.wav", np.stack([mono, mono * 0.5], axis=1), 44100)
    got = detect_file_bpm(path)
    assert got is not None and abs(got - 100) < 1.0


# -- cache ------------------------------------------------------------------------


def test_cache_round_trip_keyed_by_relative_path(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    song = write_wav(root / "music" / "a.wav", np.zeros((100, 2), np.float32), 48000)
    cache = TempoCache(tmp_path / "state" / "bpm.json", root)
    assert cache.lookup(song) == (False, None)
    cache.put(song, 96.5)
    assert cache.lookup(song) == (True, 96.5)
    cache.put(song, None)  # analyzed, nothing found: known, and not analyzed again
    assert cache.lookup(song) == (True, None)
    data = json.loads((tmp_path / "state" / "bpm.json").read_text())
    assert list(data) == ["music/a.wav"] and data["music/a.wav"]["bpm"] is None

    again = TempoCache(tmp_path / "state" / "bpm.json", root)
    assert again.lookup(song) == (True, None)
    moved = TempoCache(tmp_path / "state" / "bpm.json", tmp_path / "elsewhere")  # keys are relative to the root
    assert moved.lookup(song) == (False, None)


def test_cache_entry_dies_with_the_file_it_measured(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    song = write_wav(root / "song.wav", np.zeros((100, 2), np.float32), 48000)
    cache = TempoCache(tmp_path / "bpm.json", root)
    cache.put(song, 100.0)
    os.utime(song, (0, 0))  # a different mtime: replaced content, same size
    assert cache.lookup(song) == (False, None)
    cache.put(song, 101.0)
    write_wav(song, np.zeros((200, 2), np.float32), 48000)
    os.utime(song, (0, 0))
    assert cache.lookup(song) == (False, None)  # a different size
    song.unlink()
    assert cache.lookup(song) == (False, None)


def test_cache_ignores_junk(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    song = write_wav(root / "song.wav", np.zeros((100, 2), np.float32), 48000)
    path = tmp_path / "bpm.json"
    path.write_text("not json")
    assert TempoCache(path, root).lookup(song) == (False, None)
    stamp = song.stat()
    path.write_text(
        json.dumps(
            {
                "song.wav": {"size": stamp.st_size, "mtime": int(stamp.st_mtime), "bpm": "fast"},
                "other.wav": {"size": 1, "mtime": 1, "bpm": 90},
                7: "nope",
            }
        )
    )
    cache = TempoCache(path, root)
    assert cache.lookup(song) == (False, None)  # the bad entry was dropped
    cache.put(song, 88.0)
    assert set(json.loads(path.read_text())) == {"song.wav", "other.wav"}


# -- analyzer ---------------------------------------------------------------------


def manifest_with(root: Path, *tracks: str) -> None:
    (root / "manifest.toml").write_text("".join(f'[[music]]\nfile = "{t}"\n' for t in tracks))


def test_analyzer_measures_unknown_tracks_in_the_background(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    a = write_wav(root / "a.wav", np.zeros((100, 2), np.float32), 48000)
    write_wav(root / "b.wav", np.zeros((100, 2), np.float32), 48000)
    c = write_wav(root / "c.wav", np.zeros((100, 2), np.float32), 48000)
    (root / "manifest.toml").write_text(f'[[music]]\nfile = "a.wav"\n[[music]]\nfile = "b.wav"\nbpm = 77\n[[music]]\nfile = "{c.name}"\n')
    manifest = load_manifest(root)
    cache = TempoCache(tmp_path / "bpm.json", root)
    cache.put(c, 99.0)
    seen: list[Path] = []

    def fake_detect(path: Path) -> float | None:
        seen.append(path)
        return 123.0 if path == a else None

    analyzer = TempoAnalyzer(manifest, cache, detect=fake_detect)
    assert [m.path for m in analyzer.pending()] == [a]  # b has an override, c is cached
    assert analyzer.bpm_for(manifest.music[0]) is None
    assert analyzer.bpm_for(manifest.music[1]) == 77
    assert analyzer.bpm_for(manifest.music[2]) == 99.0

    analyzer.start()
    assert analyzer._thread is not None
    analyzer._thread.join(5.0)
    assert seen == [a]
    assert analyzer.bpm_for(manifest.music[0]) == 123.0
    assert analyzer.pending() == []
    analyzer.start()  # nothing left: no thread
    assert not analyzer.running


def test_analyzer_survives_a_failing_track(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    a = write_wav(root / "a.wav", np.zeros((100, 2), np.float32), 48000)
    b = write_wav(root / "b.wav", np.zeros((100, 2), np.float32), 48000)
    manifest_with(root, "a.wav", "b.wav")
    cache = TempoCache(tmp_path / "bpm.json", root)

    def flaky(path: Path) -> float | None:
        if path == a:
            raise RuntimeError("boom")
        return 90.0

    analyzer = TempoAnalyzer(load_manifest(root), cache, detect=flaky)
    analyzer.run()
    assert cache.lookup(a) == (False, None)  # left for next time
    assert cache.lookup(b) == (True, 90.0)


def test_analyzer_stops_between_tracks(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    write_wav(root / "a.wav", np.zeros((100, 2), np.float32), 48000)
    write_wav(root / "b.wav", np.zeros((100, 2), np.float32), 48000)
    manifest_with(root, "a.wav", "b.wav")
    cache = TempoCache(tmp_path / "bpm.json", root)
    started = threading.Event()
    analyzer: TempoAnalyzer

    def slow(path: Path) -> float | None:
        started.set()
        analyzer.stop()
        return 100.0

    analyzer = TempoAnalyzer(load_manifest(root), cache, detect=slow)
    analyzer.start()
    assert started.wait(5.0)
    analyzer._thread.join(5.0)
    assert len(json.loads((tmp_path / "bpm.json").read_text())) == 1


def test_manifest_bpm_override_is_validated(tmp_path: Path) -> None:
    root = tmp_path / "assets"
    write_wav(root / "a.wav", np.zeros((100, 2), np.float32), 48000)
    (root / "manifest.toml").write_text('[[music]]\nfile = "a.wav"\nbpm = 96.5\n')
    assert load_manifest(root).music[0].bpm == 96.5
    for bad in ("0", "-3", '"fast"', "true"):
        (root / "manifest.toml").write_text(f'[[music]]\nfile = "a.wav"\nbpm = {bad}\n')
        with pytest.raises(ManifestError):
            load_manifest(root)
