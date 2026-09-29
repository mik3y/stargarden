"""Tempo of the show tracks: basic BPM detection, a cache that outlives deploys,
and the background analyzer that fills it.

Detection is deliberately simple and dependency-free (numpy only): the track is
downmixed to mono at ~12 kHz, an onset envelope is taken as the half-wave
rectified spectral flux of a short-time spectrum, and the envelope's
autocorrelation is searched for its strongest lag inside the target tempo range.
Searching one octave of lags is what folds a track's tempo into range: a 160 BPM
track's two-beat period lands at 80. The result is good enough to pace a lighting
program roughly to the music; it is not beat tracking, and it does not know
where the downbeats are.

Results are cached in a JSON file next to the console state file
(`~/.local/state/stargarden/bpm.json` by default), outside the code and assets
directories so `just deploy`'s rsyncs leave it alone. Entries are keyed by the
file's path relative to the assets root and checked against its size and
modification time, which rsync preserves, so a re-deployed identical file keeps
its entry and a replaced one is analyzed again. A `bpm` on a manifest music
entry overrides detection for that track.
"""

import json
import logging
import math
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..manifest import Manifest, MusicEntry
from .decode import open_reader

log = logging.getLogger(__name__)

BPM_RANGE: tuple[float, float] = (70.0, 140.0)  # one octave: the fold is unambiguous except at the edges

_TARGET_RATE = 12000  # mono analysis rate; onsets live well below 6 kHz
_WINDOW = 1024  # ~85 ms at 12 kHz
_HOP = 128  # envelope at ~94 Hz
_CHUNK_FRAMES = 2048  # STFT frames per FFT batch, to keep memory flat
_MEAN_S = 1.0  # local mean removed from the envelope, so slow dynamics don't dominate the autocorrelation
_MIN_S = 8.0  # shorter than this and there is nothing to measure
_PRIOR_BPM = 100.0  # a mild pull toward the middle of the range breaks ties between a tempo and its octave at the edges
_PRIOR_OCTAVES = 1.0


def fold_bpm(bpm: float, lo: float = BPM_RANGE[0], hi: float = BPM_RANGE[1]) -> float:
    """Halve or double `bpm` until it lies in [lo, hi): a tempo and its octaves are the same beat."""
    if bpm <= 0 or not math.isfinite(bpm):
        raise ValueError(f"bpm must be positive, got {bpm}")
    while bpm >= hi:
        bpm /= 2.0
    while bpm < lo:
        bpm *= 2.0
    return bpm


# -- detection ------------------------------------------------------------------


def onset_envelope(mono: np.ndarray, rate: int) -> tuple[np.ndarray, float]:
    """Half-wave rectified, locally mean-subtracted spectral flux of `mono`, and its frame rate in Hz."""
    if len(mono) < _WINDOW + _HOP:
        return np.zeros(0, np.float32), rate / _HOP
    window = np.hanning(_WINDOW).astype(np.float32)
    frames = np.lib.stride_tricks.sliding_window_view(mono, _WINDOW)[::_HOP]
    flux = np.empty(len(frames), np.float32)
    prev: np.ndarray | None = None
    for start in range(0, len(frames), _CHUNK_FRAMES):
        chunk = frames[start : start + _CHUNK_FRAMES] * window
        spec = np.log1p(100.0 * np.abs(np.fft.rfft(chunk, axis=1)))  # compressed, so loud passages don't swamp quiet ones
        if prev is None:
            prev = spec[:1]
        diff = np.diff(np.concatenate([prev, spec]), axis=0)
        flux[start : start + len(spec)] = np.maximum(diff, 0.0).sum(axis=1)
        prev = spec[-1:]
    fps = rate / _HOP
    span = max(1, int(round(_MEAN_S * fps)))
    kernel = np.full(span, 1.0 / span, np.float32)
    local_mean = np.convolve(flux, kernel, mode="same")
    return np.maximum(flux - local_mean, 0.0).astype(np.float32), fps


def detect_bpm(mono: np.ndarray, rate: int, lo: float = BPM_RANGE[0], hi: float = BPM_RANGE[1]) -> float | None:
    """The tempo of `mono` (float32 samples at `rate` Hz) in [lo, hi) BPM, or None when
    there is too little signal to measure (silence, or under a few seconds)."""
    if lo <= 0 or hi <= lo:
        raise ValueError(f"bad tempo range {lo}-{hi}")
    env, fps = onset_envelope(mono, rate)
    n = len(env)
    if n < _MIN_S * fps or not np.any(env > 0):
        return None
    env = (env - env.mean()).astype(np.float64)
    spectrum = np.fft.rfft(env, n=2 * n)
    ac = np.fft.irfft(spectrum * np.conj(spectrum))[:n]
    if ac[0] <= 0:
        return None
    ac /= ac[0]
    lag_lo = max(2, int(math.ceil(60.0 * fps / hi)))  # fastest tempo → shortest lag
    lag_hi = min(n // 2 - 2, int(math.floor(60.0 * fps / lo)))
    if lag_hi <= lag_lo:
        return None
    # Score each candidate period with its double and its half as well (a three-tooth comb),
    # so a track whose beat lies outside the range still scores through the octave that is
    # inside it: at 60 BPM the half-beat lag is quiet, but the beat itself is the 120 candidate's
    # double.
    lags = np.arange(lag_lo - 1, lag_hi + 2)  # one extra each side for the interpolation below
    comb = ac[lags] + 0.5 * ac[2 * lags] + 0.5 * np.interp(lags / 2.0, np.arange(n), ac)
    prior = np.exp(-0.5 * (np.log2(60.0 * fps / lags / _PRIOR_BPM) / _PRIOR_OCTAVES) ** 2)
    scores = comb * prior
    k = 1 + int(np.argmax(scores[1:-1]))
    if scores[k] <= 0:
        return None
    y0, y1, y2 = scores[k - 1], scores[k], scores[k + 1]  # parabolic interpolation for a sub-frame period
    denom = y0 - 2 * y1 + y2
    lag = lags[k] + (0.5 * (y0 - y2) / denom if denom < 0 else 0.0)
    return float(fold_bpm(60.0 * fps / lag, lo, hi))


def load_mono(path: Path, target_rate: int = _TARGET_RATE) -> tuple[np.ndarray, int]:
    """The file downmixed to mono and decimated by an integer factor to about `target_rate`,
    streamed block by block so a long track never sits in memory at full rate."""
    reader = open_reader(path)
    try:
        factor = max(1, int(round(reader.samplerate / target_rate)))
        rate = reader.samplerate // factor
        blocks: list[np.ndarray] = []
        carry = np.zeros(0, np.float32)
        while True:
            block = reader.read(1 << 16)
            if len(block) == 0:
                break
            mono = np.concatenate([carry, block.mean(axis=1, dtype=np.float32)])
            whole = len(mono) - len(mono) % factor
            blocks.append(mono[:whole].reshape(-1, factor).mean(axis=1, dtype=np.float32))  # box filter: fine for onsets
            carry = mono[whole:]
        return (np.concatenate(blocks) if blocks else np.zeros(0, np.float32)), rate
    finally:
        reader.close()


def detect_file_bpm(path: Path, lo: float = BPM_RANGE[0], hi: float = BPM_RANGE[1]) -> float | None:
    mono, rate = load_mono(path)
    return detect_bpm(mono, rate, lo, hi)


# -- cache ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Stamp:
    size: int
    mtime: int  # whole seconds: what rsync is sure to preserve

    @classmethod
    def of(cls, path: Path) -> _Stamp:
        st = path.stat()
        return cls(st.st_size, int(st.st_mtime))


class TempoCache:
    """Detected tempos by track, in a JSON file; a missing or unreadable file is an empty cache.

    Entries: `{"<relative path>": {"size": N, "mtime": M, "bpm": B}}`, with `bpm` null for a
    track that was analyzed and had no measurable tempo (so it is not analyzed again)."""

    def __init__(self, path: Path, root: Path) -> None:
        self.path = path
        self.root = root
        self._entries: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load()

    def _key(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log.warning("tempo: ignoring %s: %s", self.path, e)
            return
        if not isinstance(data, dict):
            log.warning("tempo: ignoring %s: expected an object", self.path)
            return
        for key, entry in data.items():
            if not (isinstance(key, str) and isinstance(entry, dict) and _is_int(entry.get("size")) and _is_int(entry.get("mtime"))):
                continue
            bpm = entry.get("bpm")
            if bpm is not None and not (_is_number(bpm) and bpm > 0):
                continue
            self._entries[key] = {"size": entry["size"], "mtime": entry["mtime"], "bpm": None if bpm is None else float(bpm)}
        log.info("tempo: loaded %d cached track(s) from %s", len(self._entries), self.path)
        for key, entry in sorted(self._entries.items()):
            found = f"{entry['bpm']:.1f} bpm" if entry["bpm"] is not None else "no measurable tempo"
            log.info("tempo: cached %s: %s", Path(key).name, found)

    def lookup(self, path: Path) -> tuple[bool, float | None]:
        """(known, bpm): whether the file as it is now has been analyzed, and what was found."""
        try:
            stamp = _Stamp.of(path)
        except OSError:
            return False, None
        with self._lock:
            entry = self._entries.get(self._key(path))
        if entry is None or entry["size"] != stamp.size or entry["mtime"] != stamp.mtime:
            return False, None
        return True, entry["bpm"]

    def get(self, path: Path) -> float | None:
        return self.lookup(path)[1]

    def put(self, path: Path, bpm: float | None) -> None:
        stamp = _Stamp.of(path)
        with self._lock:
            self._entries[self._key(path)] = {"size": stamp.size, "mtime": stamp.mtime, "bpm": bpm}
            self._save()

    def _save(self) -> None:
        """Write atomically (temp file, then rename)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(self._entries.items())), f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


# -- the analyzer ---------------------------------------------------------------

_NICE = 10  # the analysis thread yields to the audio callback and render loop


class TempoAnalyzer:
    """Knows each show track's tempo: the manifest's `bpm` if set, else the cache, else
    nothing until `run()` has analyzed it. `start()` analyzes every unknown track on a
    background thread, one at a time, in manifest order, writing the cache as it goes."""

    def __init__(self, manifest: Manifest, cache: TempoCache, detect: Callable[[Path], float | None] = detect_file_bpm) -> None:
        self.manifest = manifest
        self.cache = cache
        self._detect = detect
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def bpm_for(self, entry: MusicEntry) -> float | None:
        if entry.bpm is not None:
            return entry.bpm
        return self.cache.get(entry.path)

    def pending(self) -> list[MusicEntry]:
        return [m for m in self.manifest.music if m.bpm is None and not self.cache.lookup(m.path)[0]]

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running or not self.pending():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, name="tempo", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        _lower_priority()
        for entry in self.pending():
            if self._stop.is_set():
                return
            started = time.monotonic()
            try:
                bpm = self._detect(entry.path)
            except Exception:
                log.exception("tempo: could not analyze %s", entry.path.name)
                continue
            took = time.monotonic() - started
            if bpm is None:
                log.warning("tempo: %s: no measurable tempo (%.1fs)", entry.title, took)
            else:
                log.info("tempo: %s: %.1f bpm (%.1fs)", entry.title, bpm, took)
            try:
                self.cache.put(entry.path, bpm)
            except OSError as e:
                log.warning("tempo: could not write %s: %s", self.cache.path, e)


def _lower_priority() -> None:
    if sys.platform != "linux":  # elsewhere a thread id is not something setpriority knows
        return
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), _NICE)  # on Linux this renices just this thread
    except OSError:
        pass
