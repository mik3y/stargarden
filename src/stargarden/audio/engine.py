"""The audio engine: owns the mixer and backend, and knows how to play the
program's three layers — ambient beds, discrete one-shots, and show music."""

import asyncio
import logging
import math
import random
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..config import AudioConfig, DiscretesConfig
from ..manifest import BedEntry, DiscreteEntry, DiscreteMotion, Manifest, MusicEntry
from .backends import make_backend
from .decode import load_clip
from .dsp import LinearResampler
from .mixer import Layer, Mixer, PointPan, Spread, Trajectory, Voice
from .sources import ClipSource, StreamSource

log = logging.getLogger(__name__)


class AudioEngine:
    def __init__(
        self,
        cfg: AudioConfig,
        discretes: DiscretesConfig,
        manifest: Manifest,
        rng: random.Random | None = None,
        on_track_finished: Callable[[], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self._discretes_cfg = discretes
        self.manifest = manifest
        self._rng = rng or random.Random()
        self._on_track_finished = on_track_finished
        levels = {Layer.BED: cfg.levels.bed, Layer.DISCRETES: cfg.levels.discretes, Layer.MUSIC: cfg.levels.music}
        self.mixer = Mixer(cfg.samplerate, levels)
        self.backend = make_backend(cfg)
        self._clips: dict[Path, np.ndarray] = {}
        self._bed_voice: Voice | None = None
        self._music_voice: Voice | None = None
        self.current_bed: BedEntry | None = None
        self.current_music: MusicEntry | None = None
        self.discretes_enabled = True

    def start(self) -> None:
        self.backend.start(self.mixer.render)

    def stop(self) -> None:
        self.backend.stop()

    # -- levels ---------------------------------------------------------------

    def level(self, layer: Layer) -> float:
        return self.mixer.level(layer)

    def set_level(self, layer: Layer, level: float) -> None:
        self.mixer.set_level(layer, level)

    def nudge_level(self, layer: Layer, delta: float) -> float:
        self.set_level(layer, self.level(layer) + delta)
        return self.level(layer)

    # -- ambient bed ----------------------------------------------------------

    @property
    def ambient_running(self) -> bool:
        return self._bed_voice is not None

    def start_ambient(self, entry: BedEntry | None = None) -> None:
        entry = entry or self.manifest.pick_bed(self._rng, avoid=self.current_bed)
        if entry is None:
            log.warning("audio: no beds in manifest")
            return
        fade = self.cfg.bed_crossfade_s
        if self._bed_voice is not None:
            self._bed_voice.fade_out(fade)
        source = StreamSource(entry.path, self.cfg.samplerate, loop=True)
        spread = Spread(rear=0.5, drift_depth=0.2, drift_period_s=120.0)
        voice = Voice(f"bed:{entry.path.stem}", source, spread, self.cfg.samplerate, gain=entry.gain, fade_in_s=fade)
        self.mixer.add(Layer.BED, voice)
        self._bed_voice = voice
        self.current_bed = entry
        log.info("audio: bed %s", entry.path.name)

    def stop_ambient(self, fade_s: float) -> None:
        if self._bed_voice is not None:
            self._bed_voice.fade_out(fade_s)
            self._bed_voice = None
            self.current_bed = None

    # -- discretes ------------------------------------------------------------

    def _clip(self, path: Path) -> np.ndarray:
        clip = self._clips.get(path)
        if clip is None:
            data, rate = load_clip(path)
            if rate != self.cfg.samplerate:
                data = LinearResampler(rate, self.cfg.samplerate).process(data)
            clip = self._clips[path] = data
        return clip

    def fire_discrete(self, entry: DiscreteEntry | None = None) -> bool:
        entry = entry or self.manifest.pick_discrete(self._rng)
        if entry is None:
            return False
        self.play_discrete(entry, self._trajectory(entry.motion, self._duration(entry)))
        log.info("audio: %s (%s)", entry.path.name, entry.motion)
        return True

    def play_thunder(self, entry: DiscreteEntry, origin: tuple[float, float], gain: float = 1.0) -> None:
        """Thunder starts at the strike and rolls a little toward the center of the space."""
        x0, y0 = origin
        duration = self._duration(entry)

        def roll(t: float) -> tuple[float, float]:
            k = 1.0 - 0.4 * min(1.0, t / duration)
            return x0 * k, y0 * k

        self.play_discrete(entry, roll, gain)
        log.info("audio: thunder %s at (%.1f, %.1f), gain %.2f", entry.path.name, x0, y0, gain)

    def play_discrete(self, entry: DiscreteEntry, trajectory: Trajectory, gain: float = 1.0) -> Voice:
        clip = self._clip(entry.path)
        voice = Voice(f"discrete:{entry.path.stem}", ClipSource(clip), PointPan(trajectory), self.cfg.samplerate, gain=entry.gain * gain)
        self.mixer.add(Layer.DISCRETES, voice)
        return voice

    def _duration(self, entry: DiscreteEntry) -> float:
        return len(self._clip(entry.path)) / self.cfg.samplerate

    def _trajectory(self, motion: DiscreteMotion, duration: float) -> Trajectory:
        rng = self._rng
        theta = rng.uniform(0, 2 * math.pi)
        radius = 0.9
        if motion is DiscreteMotion.STATIC:
            x, y = radius * math.cos(theta), radius * math.sin(theta)
            return lambda t: (x, y)
        if motion is DiscreteMotion.FLYBY:
            x0, y0 = radius * math.cos(theta), radius * math.sin(theta)
            phi = theta + math.pi + rng.uniform(-0.6, 0.6)
            x1, y1 = radius * math.cos(phi), radius * math.sin(phi)
            return lambda t: (x0 + (x1 - x0) * min(1.0, t / duration), y0 + (y1 - y0) * min(1.0, t / duration))
        sweep = rng.choice((-1, 1)) * math.pi

        def circle(t: float) -> tuple[float, float]:
            angle = theta + sweep * min(1.0, t / duration)
            return radius * math.cos(angle), radius * math.sin(angle)

        return circle

    async def run(self) -> None:
        """Schedule discrete sounds at random intervals while ambience plays."""
        cfg = self._discretes_cfg
        while True:
            await asyncio.sleep(self._rng.uniform(cfg.min_interval_s, cfg.max_interval_s))
            if self.discretes_enabled and self.ambient_running and self._music_voice is None:
                self.fire_discrete()

    # -- music ----------------------------------------------------------------

    def play_music(self, entry: MusicEntry) -> None:
        # Dual stereo: both left speakers carry L, both right speakers carry R, at equal
        # level. The beds' mirrored rear pair would put each channel on a diagonal, which
        # sums to a phantom overhead for a listener at the centre and loses the width.
        self.stop_music(fade_s=0.5)
        source = StreamSource(entry.path, self.cfg.samplerate, loop=False)
        spread = Spread(rear=0.5, swap_rear=False)
        voice = Voice(f"music:{entry.path.stem}", source, spread, self.cfg.samplerate, gain=entry.gain, fade_in_s=1.0)
        voice.on_finished = self._music_finished
        self.mixer.duck(Layer.BED, self.cfg.duck_level, self.cfg.duck_fade_s)
        self.mixer.add(Layer.MUSIC, voice)
        self._music_voice = voice
        self.current_music = entry
        log.info("audio: music %s", entry.title)

    def stop_music(self, fade_s: float) -> None:
        if self._music_voice is None:
            return
        self._music_voice.on_finished = None
        self._music_voice.fade_out(fade_s)
        self._music_voice = None
        self.current_music = None
        self.mixer.duck(Layer.BED, 1.0, self.cfg.duck_fade_s)

    def _music_finished(self, voice: Voice) -> None:
        # called on the audio thread when the track plays out
        if voice is self._music_voice:
            self._music_voice = None
            self.current_music = None
            self.mixer.duck(Layer.BED, 1.0, self.cfg.duck_fade_s)
            log.info("audio: music finished")
            if self._on_track_finished:
                self._on_track_finished()
