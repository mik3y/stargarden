"""Voices, spatializers, and the mixer that sums them into a quad frame.

`Mixer.render` runs on the audio callback thread; everything it touches is
either immutable or guarded by a short lock.
"""

import math
import threading
from collections.abc import Callable
from enum import StrEnum

import numpy as np

from .dsp import Fader
from .panner import CHANNELS, quad_gains, spread_gains
from .sources import Source

Trajectory = Callable[[float], tuple[float, float]]  # seconds → (x, y)


class Layer(StrEnum):
    BED = "bed"
    DISCRETES = "discretes"
    MUSIC = "music"


class Spatializer:
    def apply(self, block: np.ndarray, t0: float, samplerate: int) -> np.ndarray:
        """(n, 1|2) block → (n, 4) quad block; t0 is the block's start time in the voice."""
        raise NotImplementedError


class PointPan(Spatializer):
    """Mono source at a (possibly moving) point; gains interpolated across the block."""

    def __init__(self, trajectory: Trajectory) -> None:
        self._trajectory = trajectory

    def apply(self, block: np.ndarray, t0: float, samplerate: int) -> np.ndarray:
        n = len(block)
        mono = block.mean(axis=1, keepdims=True) if block.shape[1] > 1 else block
        g0 = quad_gains(*self._trajectory(t0))
        g1 = quad_gains(*self._trajectory(t0 + n / samplerate))
        ramp = np.linspace(0.0, 1.0, n, endpoint=False, dtype=np.float32)[:, None]
        return mono * (g0 + (g1 - g0) * ramp)


class Spread(Spatializer):
    """Stereo source spread front/rear, with an optional slow drift so a bed
    seems to move through the trees."""

    def __init__(self, rear: float = 0.5, drift_depth: float = 0.0, drift_period_s: float = 90.0, swap_rear: bool = True) -> None:
        self._rear = rear
        self._drift_depth = drift_depth
        self._drift_period = drift_period_s
        self._swap_rear = swap_rear

    def apply(self, block: np.ndarray, t0: float, samplerate: int) -> np.ndarray:
        rear_amount = self._rear
        if self._drift_depth:
            rear_amount += self._drift_depth * math.sin(2 * math.pi * t0 / self._drift_period)
        front, rear = spread_gains(rear_amount)
        left, right = (block[:, 0], block[:, 1]) if block.shape[1] > 1 else (block[:, 0], block[:, 0])
        out = np.empty((len(block), CHANNELS), dtype=np.float32)
        out[:, 0], out[:, 1] = left * front, right * front
        # rear pair mirrored: keeps the field decorrelated instead of a copy behind you
        rl, rr = (right, left) if self._swap_rear else (left, right)
        out[:, 2], out[:, 3] = rl * rear, rr * rear
        return out


class Voice:
    def __init__(
        self, name: str, source: Source, spatializer: Spatializer, samplerate: int, gain: float = 1.0, fade_in_s: float = 0.0
    ) -> None:
        self.name = name
        self.source = source
        self.spatializer = spatializer
        self.gain = gain
        self._samplerate = samplerate
        self._frames = 0
        self._fader = Fader(samplerate, 0.0 if fade_in_s > 0 else 1.0)
        if fade_in_s > 0:
            self._fader.set(1.0, fade_in_s)
        self._dying = False
        self.on_finished: Callable[[Voice], None] | None = None

    @property
    def elapsed(self) -> float:
        return self._frames / self._samplerate

    @property
    def finished(self) -> bool:
        return self.source.finished or (self._dying and self._fader.done)

    def fade_out(self, seconds: float) -> None:
        self._dying = True
        self._fader.set(0.0, seconds)

    def render(self, frames: int) -> np.ndarray:
        block = self.source.read(frames)
        quad = self.spatializer.apply(block, self.elapsed, self._samplerate)
        self._frames += frames
        env = self._fader.process(frames) * self.gain
        return quad * env[:, None]


class _Bus:
    def __init__(self, samplerate: int, level: float) -> None:
        self.level = Fader(samplerate, level)
        self.duck = Fader(samplerate, 1.0)
        self.voices: list[Voice] = []


class Mixer:
    def __init__(self, samplerate: int, levels: dict[Layer, float]) -> None:
        self.samplerate = samplerate
        self._buses = {layer: _Bus(samplerate, levels.get(layer, 1.0)) for layer in Layer}
        self._lock = threading.Lock()

    def add(self, layer: Layer, voice: Voice) -> None:
        with self._lock:
            self._buses[layer].voices.append(voice)

    def voices(self, layer: Layer) -> list[Voice]:
        with self._lock:
            return list(self._buses[layer].voices)

    def set_level(self, layer: Layer, level: float, seconds: float = 0.05) -> None:
        self._buses[layer].level.set(max(0.0, min(1.0, level)), seconds)

    def level(self, layer: Layer) -> float:
        return self._buses[layer].level.target

    def duck(self, layer: Layer, amount: float, seconds: float) -> None:
        self._buses[layer].duck.set(amount, seconds)

    def render(self, frames: int) -> np.ndarray:
        out = np.zeros((frames, CHANNELS), dtype=np.float32)
        finished: list[Voice] = []
        with self._lock:
            for bus in self._buses.values():
                if not bus.voices:
                    bus.level.process(frames)
                    bus.duck.process(frames)
                    continue
                acc = np.zeros((frames, CHANNELS), dtype=np.float32)
                for voice in bus.voices:
                    acc += voice.render(frames)
                    if voice.finished:
                        finished.append(voice)
                gain = bus.level.process(frames) * bus.duck.process(frames)
                out += acc * gain[:, None]
                if finished:
                    bus.voices = [v for v in bus.voices if v not in finished]
        for voice in finished:
            voice.source.close()
            if voice.on_finished:
                voice.on_finished(voice)
        np.clip(out, -1.0, 1.0, out=out)
        return out
