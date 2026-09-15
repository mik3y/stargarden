"""Sample-level helpers shared by the mixer: gain ramps and resampling."""

import numpy as np


class Fader:
    """A gain that moves linearly toward its target over a set time."""

    def __init__(self, samplerate: int, value: float = 1.0) -> None:
        self._samplerate = samplerate
        self.value = value
        self.target = value
        self._remaining = 0  # frames left in the current ramp
        self._step = 0.0

    def set(self, target: float, seconds: float = 0.0) -> None:
        self.target = target
        self._remaining = max(1, int(seconds * self._samplerate))
        self._step = (target - self.value) / self._remaining

    @property
    def done(self) -> bool:
        return self._remaining == 0

    def process(self, frames: int) -> np.ndarray:
        if self._remaining == 0:
            return np.full(frames, self.value, dtype=np.float32)
        n = min(frames, self._remaining)
        out = np.empty(frames, dtype=np.float32)
        out[:n] = self.value + self._step * np.arange(1, n + 1, dtype=np.float32)
        self._remaining -= n
        if self._remaining == 0:
            self.value = self.target
            out[n:] = self.target
        else:
            self.value = float(out[n - 1])
        return out


class LinearResampler:
    """Streaming linear resampler that stays continuous across blocks."""

    def __init__(self, rate_in: int, rate_out: int) -> None:
        self._step = rate_in / rate_out
        self._carry: np.ndarray | None = None  # last input frame of the previous block
        self._phase = 0.0  # position of the next output frame relative to carry

    def process(self, block: np.ndarray) -> np.ndarray:
        if len(block) == 0:
            return block
        if self._carry is None:
            self._carry = block[:1]
            block = block[1:]
            if len(block) == 0:
                return block
        ext = np.concatenate([self._carry, block])  # index 0 is the carry frame
        n = len(block)
        positions = np.arange(self._phase, n, self._step)
        idx = positions.astype(np.int64)
        frac = (positions - idx).astype(np.float32)[:, None]
        out = ext[idx] * (1.0 - frac) + ext[idx + 1] * frac
        self._phase = (positions[-1] + self._step - n) if len(positions) else (self._phase - n)
        self._carry = block[-1:]
        return out.astype(np.float32)
